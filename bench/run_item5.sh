#!/usr/bin/env bash
# Item 5 rerun (Review 3): per-syscall overhead microbenchmark, all four
# conditions, 10 runs x 50,000 iterations each, in one session.
#
# Writes a FRESH file bench/results_item5.csv and never touches
# bench/results.csv (the paper's session-B data).
#
# naive_perevent gets a per-run tracer so each run has its own RESULT line.
# A naive run is INVALID when:
#     ns/syscall < 10 x baseline mean      (tracer almost certainly not attached)
#  OR the tracer's RESULT shows exported=0 (tracer attached but captured nothing)
# Invalid runs are rerun (up to MAXRETRY attempts); EVERY attempt, valid or not,
# is written to the CSV with a valid=0/1 flag.
#
# usage: bash bench/run_item5.sh [container] [runs] [iters]
set -u
C=${1:-demo}
RUNS=${2:-10}
ITERS=${3:-50000}
MAXRETRY=${MAXRETRY:-12}
OUT=bench/results_item5.csv
cd "$(dirname "$0")/.."

[ -x bench/syscall_bench ] || { echo "build first: gcc -O2 -static -o bench/syscall_bench bench/syscall_bench.c"; exit 1; }
sudo -n true || exit 1   # passwordless gate
docker start "$C" >/dev/null
docker cp bench/syscall_bench "$C":/tmp/syscall_bench >/dev/null
docker update --cpuset-cpus 2 "$C" >/dev/null && echo "pinned $C to cpu 2"
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

echo "ts,condition,run,attempt,ns_per_syscall,syscalls_per_sec,exported,valid" > "$OUT"

DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  sudo -n pkill -9 -f "ebpf/tracer.py|ebpf/tracer_unigram.py|ebpf/naive_tracer.py|syscall_bench" 2>/dev/null
  docker update --cpuset-cpus 0-3 "$C" >/dev/null 2>&1 && echo "unpinned $C"
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted - cleaning up"; exit 130' INT TERM

tracer_pid() { pgrep -n -f "^python3 -u ebpf/"; }
bench_run() { docker exec "$C" /tmp/syscall_bench "$ITERS" | tail -1; }

echo "container=$C runs=$RUNS iters=$ITERS -> $OUT"
echo

# --- baseline (no tracer) ---
echo "=== baseline ==="
base_vals=()
for i in $(seq "$RUNS"); do
  line=$(bench_run); ns=$(echo "$line" | cut -d, -f3); sps=$(echo "$line" | cut -d, -f4)
  base_vals+=("$ns")
  echo "$(date +%s),baseline,$i,1,$ns,$sps,,1" >> "$OUT"
  printf "  baseline run%-3s %11s ns/syscall\n" "$i" "$ns"
done
BASE_MEAN=$(printf '%s\n' "${base_vals[@]}" | awk '{s+=$1;n++} END{printf "%.4f", s/n}')
THRESH=$(awk "BEGIN{printf \"%.4f\", 10*$BASE_MEAN}")
echo "baseline mean = $BASE_MEAN ns   naive validity threshold (10x) = $THRESH ns"
echo

# --- in-kernel tracers: one tracer for all RUNS runs (paper method) ---
run_inkernel() {   # $1 = condition name, $2 = tracer script
  local name=$1 script=$2 LOGF py i ns sps alive
  [ -f "$script" ] || { echo "missing $script - skipping $name"; return; }
  echo "=== $name ==="
  LOGF=$(mktemp)
  sudo -n python3 -u "$script" "$C" /tmp/_item5_trace.csv < /dev/null > "$LOGF" 2>&1 &
  echo -n "  attaching"
  local ok=0
  for _ in $(seq 90); do
    grep -qE "READY|cgroup_id=" "$LOGF" 2>/dev/null && { echo " ok"; ok=1; break; }
    sleep 1; echo -n "."
  done
  [ "$ok" = 1 ] || { echo " FAILED"; tail -5 "$LOGF"; return; }
  sleep 2
  for i in $(seq "$RUNS"); do
    py=$(tracer_pid)
    alive=1; { [ -n "$py" ] && kill -0 "$py" 2>/dev/null; } || alive=0
    line=$(bench_run); ns=$(echo "$line" | cut -d, -f3); sps=$(echo "$line" | cut -d, -f4)
    echo "$(date +%s),$name,$i,1,$ns,$sps,,$alive" >> "$OUT"
    printf "  %s run%-3s %11s ns/syscall  attached=%s\n" "$name" "$i" "$ns" "$alive"
  done
  py=$(tracer_pid); [ -n "$py" ] && sudo -n kill -INT "$py" 2>/dev/null; sleep 2
  py=$(tracer_pid); [ -n "$py" ] && sudo -n kill -9 "$py" 2>/dev/null; sleep 1
}
run_inkernel in_kernel_unigram ebpf/tracer_unigram.py
echo
run_inkernel in_kernel ebpf/tracer.py
echo

# --- naive_perevent: per-run tracer + validity check + rerun ---
echo "=== naive_perevent (invalid if ns<${THRESH} or exported=0; rerun invalid) ==="
for i in $(seq "$RUNS"); do
  attempt=0
  while :; do
    attempt=$((attempt + 1))
    LOGF=$(mktemp)
    sudo -n python3 -u ebpf/naive_tracer.py "$C" < /dev/null > "$LOGF" 2>&1 &
    ok=0
    for _ in $(seq 90); do grep -q "READY" "$LOGF" 2>/dev/null && { ok=1; break; }; sleep 1; done
    [ "$ok" = 1 ] || echo "    (run $i attempt $attempt: tracer attach not confirmed)"
    sleep 2
    line=$(bench_run); ns=$(echo "$line" | cut -d, -f3); sps=$(echo "$line" | cut -d, -f4)
    py=$(tracer_pid); [ -n "$py" ] && sudo -n kill -INT "$py" 2>/dev/null; sleep 2
    py=$(tracer_pid); [ -n "$py" ] && sudo -n kill -9 "$py" 2>/dev/null
    exported=$(grep -oE "exported=[0-9]+" "$LOGF" | head -1 | cut -d= -f2); exported=${exported:-0}
    valid=1
    [ -z "$ns" ] && ns=0
    awk "BEGIN{exit !($ns < $THRESH)}" && valid=0        # ns below 10x baseline
    [ "$exported" = 0 ] && valid=0                        # tracer captured nothing
    echo "$(date +%s),naive_perevent,$i,$attempt,$ns,$sps,$exported,$valid" >> "$OUT"
    printf "  naive run%-3s attempt%-2s %13s ns/syscall  exported=%-9s valid=%s\n" \
      "$i" "$attempt" "$ns" "$exported" "$valid"
    [ "$valid" = 1 ] && break
    [ "$attempt" -ge "$MAXRETRY" ] && { echo "    run $i: still invalid after $MAXRETRY attempts, moving on"; break; }
  done
done

cleanup
echo
echo "=== medians over VALID runs ==="
python3 - "$OUT" "$BASE_MEAN" <<'PY'
import csv, statistics, sys, collections
rows = list(csv.DictReader(open(sys.argv[1])))
valid = collections.defaultdict(list); allc = collections.defaultdict(list)
exp = collections.defaultdict(list)
for r in rows:
    allc[r["condition"]].append(r)
    if r["valid"] == "1":
        valid[r["condition"]].append(float(r["ns_per_syscall"]))
    if r["exported"]:
        exp[r["condition"]].append(int(r["exported"]))
base = statistics.median(valid["baseline"]) if valid["baseline"] else float(sys.argv[2])
for c in ("baseline", "in_kernel_unigram", "in_kernel", "naive_perevent"):
    if c not in allc: continue
    v = valid[c]; n_all = len(allc[c]); n_inv = sum(1 for r in allc[c] if r["valid"] != "1")
    if v:
        m = statistics.median(v)
        extra = f"  exported median={statistics.median(exp[c]):.0f}" if exp[c] else ""
        print(f"  {c:18s} median {m:12.2f} ns  valid={len(v):2d}/{n_all:<2d} invalid={n_inv}"
              f"  +{m-base:11.2f} ns  {m/base:7.2f}x{extra}")
    else:
        print(f"  {c:18s} NO VALID RUNS ({n_all} attempts)")
PY
echo
echo "results -> $OUT  (bench/results.csv untouched)"
