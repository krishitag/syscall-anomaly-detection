#!/usr/bin/env bash
# Review 3: capture 3 INDEPENDENT evaluation runs.
#   run i: tracer + nginx traffic (seed 100+i, ~200 s) + all 9 attacks
#   -> data/eval_run{1,2,3}.csv  and  data/attack_log_run{1,2,3}.csv
#
# Never writes data/eval.csv or data/attack_log.csv (hard-guarded below).
# Container left UNPINNED (matches the training/eval captures). Restores
# data/pair_survey.json, which the tracer rewrites on exit.
#
# usage: bash bench/eval_runs.sh [container]   (needs sudo for the tracer)
set -u
C=${1:-demo}
DUR=${DUR:-200}      # traffic seconds per run
WARMUP=${WARMUP:-20} # normal traffic before attacks start
cd "$(dirname "$0")/.."

sudo -n true || exit 1   # passwordless gate (sudo -v needs a tty under mixed sudoers rules)
docker start "$C" >/dev/null
docker update --cpuset-cpus 0-3 "$C" >/dev/null
mkdir -p data
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

TRACER_LOG=""; TRAFFIC_PID=""; ATTACK_PID=""; DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  [ -n "$TRAFFIC_PID" ] && kill "$TRAFFIC_PID" 2>/dev/null
  [ -n "$ATTACK_PID" ]  && kill "$ATTACK_PID"  2>/dev/null
  pkill -f normal_traffic.py 2>/dev/null
  pkill -f workload/attack.sh 2>/dev/null
  sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null; sleep 1
  sudo -n pkill -9  -f "ebpf/tracer.py" 2>/dev/null
  docker update --cpuset-cpus 0-3 "$C" >/dev/null 2>&1
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted - cleaning up"; exit 130' INT TERM

one_run() {
  local i=$1
  local seed=$((100 + i))
  local eval_csv="data/eval_run${i}.csv"
  local attack_log="data/attack_log_run${i}.csv"

  # Hard guard: never clobber the canonical captures.
  case "$eval_csv$attack_log" in
    *data/eval.csv*|*data/attack_log.csv) echo "REFUSING to write $eval_csv/$attack_log"; exit 2;;
  esac

  echo "=========================================================="
  echo "RUN $i  seed=$seed  dur=${DUR}s  -> $eval_csv  $attack_log"
  echo "=========================================================="

  TRACER_LOG=$(mktemp)
  sudo -n python3 -u ebpf/tracer.py "$C" "$eval_csv" < /dev/null > "$TRACER_LOG" 2>&1 &
  echo -n "  attaching tracer"
  local ok=0
  for _ in $(seq 90); do
    grep -qE "READY|cgroup_id=" "$TRACER_LOG" 2>/dev/null && { echo " ok"; ok=1; break; }
    sleep 1; echo -n "."
  done
  [ "$ok" = 1 ] || { echo " FAILED"; tail -5 "$TRACER_LOG"; exit 1; }
  sleep 2

  python3 workload/normal_traffic.py "$C" "$DUR" "$seed" < /dev/null > /tmp/_eval_traffic_$i.log 2>&1 &
  TRAFFIC_PID=$!
  echo "  traffic started (pid $TRAFFIC_PID), warmup ${WARMUP}s before attacks"
  sleep "$WARMUP"

  GAP=${GAP:-12} LOG="$attack_log" bash workload/attack.sh "$C" > /tmp/_eval_attack_$i.log 2>&1 &
  ATTACK_PID=$!
  echo "  attacks started (pid $ATTACK_PID)"

  wait "$TRAFFIC_PID" 2>/dev/null; TRAFFIC_PID=""
  wait "$ATTACK_PID"  2>/dev/null; ATTACK_PID=""
  echo "  traffic + attacks done"

  sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null; sleep 2
  sudo -n pkill -9  -f "ebpf/tracer.py" 2>/dev/null; sleep 1
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json

  local rows; rows=$(($(wc -l < "$eval_csv") - 1))
  local atks; atks=$(($(wc -l < "$attack_log") - 1))
  echo "  wrote $eval_csv ($rows windows), $attack_log ($atks attacks)"
}

for i in 1 2 3; do one_run "$i"; done
cleanup
echo
echo "=== summary ==="
for i in 1 2 3; do
  printf "run%s: %6s windows   %s attacks\n" "$i" \
    "$(($(wc -l < data/eval_run${i}.csv) - 1))" \
    "$(($(wc -l < data/attack_log_run${i}.csv) - 1))"
done
echo "eval.csv / attack_log.csv untouched:"; ls -l data/eval.csv data/attack_log.csv
