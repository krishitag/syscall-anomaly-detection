#!/usr/bin/env bash
# Per-syscall overhead microbenchmark.
# usage: bash bench/run_all.sh [container] [runs] [iterations] [conditions]
#   conditions: comma list of baseline,in_kernel,in_kernel_unigram,naive_perevent
#               default: baseline,in_kernel,in_kernel_unigram   (naive is slow, run it separately)
set -u
C=${1:-demo}
RUNS=${2:-10}
ITERS=${3:-5000000}
ONLY=${4:-baseline,in_kernel,in_kernel_unigram}
OUT=bench/results.csv
cd "$(dirname "$0")/.."
mkdir -p bench

[ -x bench/syscall_bench ] || { echo "build first: gcc -O2 -static -o bench/syscall_bench bench/syscall_bench.c"; exit 1; }
sudo -v || exit 1
docker start "$C" >/dev/null
docker cp bench/syscall_bench "$C":/tmp/syscall_bench >/dev/null
docker update --cpuset-cpus 2 "$C" >/dev/null && echo "pinned $C to cpu 2"
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

[ -f "$OUT" ] || echo "ts,condition,run,ns_per_syscall,syscalls_per_sec,collector_cpu_pct,collector_rss_kb" > "$OUT"

LOGF=""
DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  sudo -n pkill -9 -f "ebpf/tracer.py|ebpf/tracer_unigram.py|ebpf/naive_tracer.py|syscall_bench" 2>/dev/null
  docker update --cpuset-cpus 0-3 "$C" >/dev/null 2>&1 && echo "unpinned $C"
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted - cleaning up"; exit 130' INT TERM

want() { [[ ",$ONLY," == *",$1,"* ]]; }
tracer_pid() { pgrep -n -f "^python3 -u ebpf/"; }

start_tracer() {   # $1 = script, $2 = label
  LOGF=$(mktemp)
  sudo -n python3 -u "$1" "$C" /tmp/_bench_trace.csv < /dev/null > "$LOGF" 2>&1 &
  echo -n "  attaching $2"
  for _ in $(seq 90); do
    grep -qE "READY|cgroup_id=" "$LOGF" 2>/dev/null && { echo " ok"; sleep 2; return 0; }
    sleep 1; echo -n "."
  done
  echo " FAILED"; tail -5 "$LOGF"; exit 1
}

stop_tracer() {
  local py; py=$(tracer_pid)
  [ -n "$py" ] && sudo -n kill -INT "$py" 2>/dev/null
  sleep 2
  [ -n "$py" ] && sudo -n kill -9 "$py" 2>/dev/null
  grep -E "RESULT" "$LOGF" || true
}

collector_stats() {
  local py; py=$(tracer_pid)
  [ -z "$py" ] && { echo ","; return; }
  ps -o %cpu=,rss= -p "$py" 2>/dev/null | awk '{print $1","$2}'
}

run_condition() {
  echo "=== $1 ==="
  for i in $(seq "$RUNS"); do
    line=$(docker exec "$C" /tmp/syscall_bench "$ITERS" | tail -1)
    nsps=$(echo "$line" | cut -d, -f3)
    sps=$(echo "$line" | cut -d, -f4)
    stats=$(collector_stats)
    echo "$(date +%s),$1,$i,$nsps,$sps,$stats" >> "$OUT"
    printf "  run%-3s %11s ns/syscall   collector cpu%%,rss_kb = %s\n" "$i" "$nsps" "$stats"
  done
}

echo "container=$C runs=$RUNS iters=$ITERS conditions=$ONLY -> $OUT"
echo

want baseline           && run_condition baseline
if want in_kernel; then
  start_tracer ebpf/tracer.py in-kernel;                 run_condition in_kernel;         stop_tracer
fi
if want in_kernel_unigram; then
  [ -f ebpf/tracer_unigram.py ] || { echo "missing ebpf/tracer_unigram.py"; exit 1; }
  start_tracer ebpf/tracer_unigram.py in-kernel-unigram; run_condition in_kernel_unigram; stop_tracer
fi
if want naive_perevent; then
  start_tracer ebpf/naive_tracer.py naive;               run_condition naive_perevent;    stop_tracer
fi

echo; echo "=== medians ==="
python3 - "$OUT" <<'PY'
import csv, statistics, sys, collections
d = collections.defaultdict(list); cpu = collections.defaultdict(list); rss = collections.defaultdict(list)
for r in csv.DictReader(open(sys.argv[1])):
    d[r["condition"]].append(float(r["ns_per_syscall"]))
    if r["collector_cpu_pct"]: cpu[r["condition"]].append(float(r["collector_cpu_pct"]))
    if r["collector_rss_kb"]:  rss[r["condition"]].append(float(r["collector_rss_kb"]))
base = statistics.median(d["baseline"]) if "baseline" in d else 1
for c in ("baseline", "in_kernel_unigram", "in_kernel", "naive_perevent"):
    if c in d:
        m = statistics.median(d[c])
        extra = ""
        if cpu[c]: extra = f"  cpu {statistics.median(cpu[c]):5.1f}%  rss {statistics.median(rss[c])/1024:6.1f} MB"
        print(f"  {c:18s} {m:11.2f} ns  n={len(d[c]):3d}  +{m-base:11.2f} ns  {m/base:7.2f}x{extra}")
PY