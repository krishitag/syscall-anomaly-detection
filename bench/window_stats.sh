#!/usr/bin/env bash
# Distinct / total syscalls per 2 s window, and BPF map entries per read,
# under normal traffic with the 5 attacks mixed in.
# usage: bash bench/window_stats.sh [container] [seconds]
set -u
C=${1:-demo}; DUR=${2:-120}
cd "$(dirname "$0")/.."
sudo -v || exit 1
docker start "$C" >/dev/null
docker update --cpuset-cpus 0-3 "$C" >/dev/null
OUTLOG=bench/window_stats.log
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  pkill -f normal_traffic.py 2>/dev/null
  sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null; sleep 1
  sudo -n pkill -9  -f "ebpf/tracer.py" 2>/dev/null
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted - cleaning up"; exit 130' INT TERM

sudo -n python3 -u ebpf/tracer.py "$C" /tmp/_window_stats.csv < /dev/null > "$OUTLOG" 2>&1 &
echo -n "attaching"; until grep -q "cgroup_id=" "$OUTLOG" 2>/dev/null; do sleep 1; echo -n "."; done; echo " ok"

python3 workload/normal_traffic.py "$C" "$DUR" 11 > /dev/null 2>&1 &
TRAFFIC=$!
sleep 20
echo "running attacks (log kept out of data/)..."
LOG=/tmp/_ws_attack_log.csv bash workload/attack.sh "$C" > /dev/null 2>&1
echo "waiting for traffic to finish..."
wait "$TRAFFIC"
cleanup

python3 - "$OUTLOG" <<'PY'
import re, sys, statistics
rows = [tuple(map(int, m.groups())) for line in open(sys.argv[1])
        if (m := re.search(r"distinct=(\d+) total=(\d+) map=(\d+)/(\d+)", line))]
act = [r for r in rows if r[1] > 0]
def s(i, rs):
    v = [r[i] for r in rs]
    return f"mean {statistics.mean(v):8.1f}   median {statistics.median(v):6.0f}   max {max(v)}"
print(f"\nwindows: {len(rows)} (2 s span each; non-idle: {len(act)})")
print("distinct syscall numbers / window (non-idle):", s(0, act))
print("total syscalls / window (non-idle):          ", s(1, act))
print("unigram map entries per read:                ", s(2, rows))
print("bigram map entries per read:                 ", s(3, rows))
PY