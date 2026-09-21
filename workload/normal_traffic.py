"""
Varied, realistic-ish traffic against the demo nginx container.
usage: python3 workload/normal_traffic.py [container] [seconds] [seed]
"""
import random, subprocess, sys, threading, time
import urllib.request, urllib.error

container = sys.argv[1] if len(sys.argv) > 1 else "demo"
duration  = float(sys.argv[2]) if len(sys.argv) > 2 else 600
random.seed(int(sys.argv[3]) if len(sys.argv) > 3 else 17)

ip = subprocess.check_output(
    ["docker", "inspect", "-f",
     "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container],
    text=True).strip()
BASE = f"http://{ip}"

PATHS = [("/", 50), ("/index.html", 20), ("/50x.html", 5), ("/favicon.ico", 8),
         ("/missing", 7), ("/a/b/c.php", 5), ("/?q=search", 5)]
paths, weights = zip(*PATHS)

stats = {"ok": 0, "404": 0, "err": 0}
lock = threading.Lock()

def hit():
    try:
        urllib.request.urlopen(BASE + random.choices(paths, weights)[0], timeout=3).read()
        k = "ok"
    except urllib.error.HTTPError:
        k = "404"
    except Exception:
        k = "err"
    with lock:
        stats[k] += 1

def steady(seconds, rate):
    end = time.time() + seconds
    while time.time() < end:
        hit()
        time.sleep(random.expovariate(rate))  # random gaps averaging 1/rate

def burst(clients, per_client):
    ts = [threading.Thread(target=lambda: [hit() for _ in range(per_client)])
          for _ in range(clients)]
    for t in ts: t.start()
    for t in ts: t.join()

deadline = time.time() + duration
while time.time() < deadline:
    left = deadline - time.time()
    phase = random.choices(["idle", "light", "busy", "burst"], [2, 4, 3, 1])[0]
    if phase == "idle":
        time.sleep(min(left, random.uniform(2, 10)))
    elif phase == "light":
        steady(min(left, random.uniform(10, 30)), random.uniform(1, 5))
    elif phase == "busy":
        steady(min(left, random.uniform(5, 20)), random.uniform(20, 60))
    else:
        burst(random.randint(5, 20), random.randint(5, 20))
    print(f"[{time.strftime('%T')}] {phase:5s} ok={stats['ok']} "
          f"404={stats['404']} err={stats['err']}", flush=True)