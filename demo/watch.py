#!/usr/bin/env python3
"""
Live anomaly watcher.

Tails the CSV that ebpf/tracer.py is writing and scores each 1-second window
as soon as it appears, printing NORMAL or ALERT.

Runs as a separate process from the tracer on purpose: the collection layer
stays independent of the ML stack, and root never has to load torch.

usage:
    terminal 1:  sudo python3 ebpf/tracer.py demo data/live.csv
    terminal 2:  python3 demo/watch.py data/live.csv
"""
import csv, os, sys, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from member2.pipeline import prepare_window
from person3_ml.detect import score_window, anomaly_threshold

# Display only. Kept inline rather than importing ebpf.vocab, which pulls in
# bcc; the watcher deliberately has no kernel-side dependencies.
NAMES = ["read", "write", "recvfrom", "openat", "close",
         "mmap", "munmap", "execve", "epoll_wait", "clone",
         "connect", "accept4", "socket", "setns", "unshare",
         "ptrace", "fchmodat", "fchownat", "kill", "sendfile"]
SECURITY = {"execve", "clone", "connect", "socket", "setns",
            "unshare", "ptrace", "fchmodat", "fchownat", "kill"}

path = sys.argv[1] if len(sys.argv) > 1 else "data/live.csv"

while not os.path.exists(path):
    print(f"waiting for {path} ...")
    time.sleep(1)

threshold = anomaly_threshold()
print(f"threshold = {threshold:.6f}")
print(f"watching {path}   (Ctrl+C to stop)\n")

f = open(path, "r", newline="")

# read the header, waiting for it if the tracer hasn't flushed it yet
header = None
while header is None:
    line = f.readline()
    if line.strip():
        header = next(csv.reader([line]))
    else:
        time.sleep(0.2)

buf = ""
n = alerts = 0
try:
    while True:
        chunk = f.readline()
        if not chunk:
            time.sleep(0.2)
            continue
        buf += chunk
        if not buf.endswith("\n"):
            continue  # partial line: wait for the rest
        raw, buf = buf, ""

        try:
            row = dict(zip(header, next(csv.reader([raw]))))
            err = score_window(prepare_window(row))
        except Exception as e:
            print(f"  skipped a row: {type(e).__name__}: {e}")
            continue

        n += 1
        stamp = time.strftime("%H:%M:%S")

        counts = {}
        for i, name in enumerate(NAMES, 1):
            v = int(row.get(f"syscall_{i:02d}_count", 0) or 0)
            if v:
                counts[name] = v
        sec = " ".join(f"{k}={v}" for k, v in counts.items() if k in SECURITY)

        if err > threshold:
            alerts += 1
            print(f"{stamp}  err={err:.6f}  *** ALERT ***  {sec or '-'}")
        else:
            busy = sum(counts.values())
            print(f"{stamp}  err={err:.6f}  normal        "
                  f"{'idle' if not busy else f'{busy} syscalls'}")
except KeyboardInterrupt:
    print(f"\n{n} windows scored, {alerts} alerts")