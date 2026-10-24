#!/usr/bin/env python3
"""High-concurrency closed-loop HTTP benchmark.

Unlike bench.py (one connection), this opens CONC persistent connections and
keeps each one issuing GET / in a loop for DURATION seconds, then reports
aggregate throughput and latency percentiles for one container.

usage: python3 bench/bench_concurrent.py <container> [conc] [duration_s]
"""
import http.client
import statistics
import subprocess
import sys
import threading
import time

container = sys.argv[1] if len(sys.argv) > 1 else "demo"
CONC = int(sys.argv[2]) if len(sys.argv) > 2 else 50
DURATION = float(sys.argv[3]) if len(sys.argv) > 3 else 15.0

ip = subprocess.check_output(
    ["docker", "inspect", "-f",
     "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container],
    text=True).strip()

lat = [[] for _ in range(CONC)]
counts = [0] * CONC
errs = [0] * CONC
start_evt = threading.Event()


def worker(k, deadline):
    c = http.client.HTTPConnection(ip, 80, timeout=5)
    start_evt.wait()
    while time.perf_counter() < deadline:
        a = time.perf_counter()
        try:
            c.request("GET", "/")
            c.getresponse().read()
            lat[k].append((time.perf_counter() - a) * 1000)
            counts[k] += 1
        except Exception:
            errs[k] += 1
            try:
                c.close()
                c = http.client.HTTPConnection(ip, 80, timeout=5)
            except Exception:
                pass
    c.close()


deadline = time.perf_counter() + DURATION
threads = [threading.Thread(target=worker, args=(k, deadline)) for k in range(CONC)]
for t in threads:
    t.start()
t0 = time.perf_counter()
start_evt.set()
for t in threads:
    t.join()
elapsed = time.perf_counter() - t0

all_lat = sorted(x for sub in lat for x in sub)
total = sum(counts)
total_err = sum(errs)
rps = total / elapsed
p50 = all_lat[len(all_lat) // 2] if all_lat else float("nan")
p99 = all_lat[int(len(all_lat) * 0.99)] if all_lat else float("nan")
print(f"{container:14s} conc={CONC} dur={elapsed:.1f}s  reqs={total} err={total_err}  "
      f"rps={rps:8.1f}  p50={p50:.3f}ms  p99={p99:.3f}ms")
