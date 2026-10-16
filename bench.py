#!/usr/bin/env python3
"""Closed-loop HTTP benchmark. usage: python3 bench.py <label> [runs] [reqs]"""
import http.client, json, statistics, subprocess, sys, time

label = sys.argv[1]
RUNS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
N = int(sys.argv[3]) if len(sys.argv) > 3 else 3000

ip = subprocess.check_output(
    ["docker", "inspect", "-f",
     "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", "demo"],
    text=True).strip()

def run():
    c = http.client.HTTPConnection(ip, 80, timeout=5)
    lat = []
    t0 = time.perf_counter()
    for _ in range(N):
        a = time.perf_counter()
        c.request("GET", "/")
        c.getresponse().read()
        lat.append((time.perf_counter() - a) * 1000)
    total = time.perf_counter() - t0
    c.close()
    lat.sort()
    return {"rps": N / total,
            "p50": lat[len(lat)//2],
            "p99": lat[int(len(lat)*0.99)]}

print(f"warmup..."); run()
res = []
for i in range(RUNS):
    r = run()
    res.append(r)
    print(f"run{i+1}  rps={r['rps']:8.1f}  p50={r['p50']:.3f}ms  p99={r['p99']:.3f}ms")

out = {"label": label, "runs": RUNS, "requests_per_run": N,
       "rps_mean": statistics.mean(x["rps"] for x in res),
       "rps_stdev": statistics.pstdev([x["rps"] for x in res]),
       "p50_mean": statistics.mean(x["p50"] for x in res),
       "p99_mean": statistics.mean(x["p99"] for x in res)}
print(f"\n{label}: rps={out['rps_mean']:.1f} (sd {out['rps_stdev']:.1f})  "
      f"p50={out['p50_mean']:.3f}ms  p99={out['p99_mean']:.3f}ms")
open("data/bench.jsonl", "a").write(json.dumps(out) + "\n")