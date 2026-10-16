#!/usr/bin/env python3
"""Answers: unshare visibility (item 2) and detection delay (item 3)."""
import csv, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from member2.pipeline import prepare_aggregated_csv
from person3_ml.detect import reconstruction_errors, anomaly_threshold

EVAL = sys.argv[1] if len(sys.argv) > 1 else "data/eval.csv"
LOG = sys.argv[2] if len(sys.argv) > 2 else "data/attack_log.csv"

rows = list(csv.DictReader(open(EVAL)))
errs = reconstruction_errors(prepare_aggregated_csv(EVAL).X)
th = anomaly_threshold()
attacks = list(csv.DictReader(open(LOG)))

print(f"threshold {th:.6f}   windows {len(rows)}   attacks {len(attacks)}\n")

SEC = {8: "execve", 10: "clone", 11: "connect", 13: "socket", 14: "setns",
       15: "unshare", 16: "ptrace", 17: "fchmodat", 18: "fchownat", 19: "kill"}

print("=== per attack ===")
for a in attacks:
    s, e = int(a["start_ns"]), int(a["end_ns"])
    idx = [i for i, r in enumerate(rows)
           if int(r["window_end_ns"]) > s and int(r["window_start_ns"]) < e]
    agg = {}
    for i in idx:
        for c, name in SEC.items():
            v = int(rows[i][f"syscall_{c:02d}_count"] or 0)
            if v:
                agg[name] = agg.get(name, 0) + v
    flagged = [i for i in idx if errs[i] > th]

    delay = None
    for i, r in enumerate(rows):
        if int(r["window_end_ns"]) >= s and errs[i] > th:
            delay = (int(r["window_end_ns"]) - s) / 1e9
            break
    print(f"\n{a['attack']:16s} windows={len(idx)} flagged={len(flagged)}"
          f" delay={'%.2fs' % delay if delay is not None else 'NOT DETECTED'}")
    print(f"  security syscalls: {agg or 'none'}")

tot = sum(int(r["syscall_15_count"] or 0) for r in rows)
nz = sum(1 for r in rows if int(r["syscall_15_count"] or 0))
print(f"\n=== unshare (syscall_15_count) whole capture: total={tot} "
      f"in {nz} windows ===")
print("-> seccomp BLOCKED it (invisible to sys_enter)" if tot == 0
      else "-> unshare IS visible to the tracepoint")