#!/usr/bin/env bash
# usage: bash bench/run_all.sh [container] [runs] [iterations] [only_condition]
#   only_condition: baseline | in_kernel | naive_perevent | all  (default all)
set -u
C=${1:-demo}
RUNS=${2:-10}
ITERS=${3:-5000000}
ONLY=${4:-all}
OUT=bench/results.csv
mkdir -p bench

[ -x bench/syscall_bench ] || { echo "build first: gcc -O2 -static -o bench/syscall_bench bench/syscall_bench.c"; exit 1; }
docker cp bench/syscall_bench "$C":/tmp/syscall_bench >/dev/null
docker update --cpuset-cpus 2 "$C" >/dev/null 2>&1 && echo "pinned $C to cpu 2"

[ -f "$OUT" ] || echo "ts,condition,run,ns_per_syscall,syscalls_per_sec,collector_cpu_pct,collector_rss_kb" > "$OUT"

TRACER_PID=""; LOGF=""

start_tracer() {
  LOGF=$(mktemp)
  sudo python3 -u "$1" "$C" > "$LOGF" 2>&1 &
  TRACER_PID=$!
  echo -n "  attaching $2"
  for _ in $(seq 90); do
    grep -qE "READY|cgroup_id=" "$LOGF" 2>/dev/null && { echo " ok"; sleep 2; return 0; }
    sleep 1; echo -n "."
  done
  echo " FAILED"; tail -5 "$LOGF"; exit 1
}

stop_tracer() {
  [ -z "$TRACER_PID" ] && return
  sudo pkill -TERM -P "$TRACER_PID" 2>/dev/null
  sudo kill -TERM "$TRACER_PID" 2>/dev/null
  sleep 2
  echo "  --- tracer output ---"
  grep -E "RESULT" "$LOGF" || echo "  (no result line)"
  TRACER_PID=""
}

collector_stats() {
  [ -z "$TRACER_PID" ] && { echo ","; return; }
  local kid; kid=$(pgrep -P "$TRACER_PID" | head -1); [ -z "$kid" ] && kid="$TRACER_PID"
  ps -o %cpu=,rss= -p "$kid" 2>/dev/null | awk '{print $1","$2}' || echo ","
}

run_condition() {
  echo "=== $1 ==="
  for i in $(seq "$RUNS"); do
    line=$(docker exec "$C" /tmp/syscall_bench "$ITERS" | tail -1)
    printf "%s,%s,%s,%s,%s,%s\n" "$(date +%s)" "$1" "$i" \
      "$(echo "$line" | cut -d, -f3)" "$(echo "$line" | cut -d, -f4)" "$(collector_stats)" >> "$OUT"
    printf "  run%-3s %9s ns/syscall\n" "$i" "$(echo "$line" | cut -d, -f3)"
  done
}

[ "$ONLY" = all ] || [ "$ONLY" = baseline ] && run_condition baseline
if [ "$ONLY" = all ] || [ "$ONLY" = in_kernel ]; then
  start_tracer ebpf/tracer.py in-kernel; run_condition in_kernel; stop_tracer
fi
if [ "$ONLY" = all ] || [ "$ONLY" = naive_perevent ]; then
  start_tracer ebpf/naive_tracer.py naive; run_condition naive_perevent; stop_tracer
fi

echo; echo "=== medians ==="
python3 - "$OUT" <<'PY'
import csv, statistics, sys, collections
d = collections.defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    d[r["condition"]].append(float(r["ns_per_syscall"]))
base = statistics.median(d["baseline"]) if "baseline" in d else 1
for c in ("baseline", "in_kernel", "naive_perevent"):
    if c in d:
        m = statistics.median(d[c])
        print(f"  {c:16s} {m:9.2f} ns  n={len(d[c]):3d}  +{m-base:8.2f} ns  {m/base:5.2f}x")
PY