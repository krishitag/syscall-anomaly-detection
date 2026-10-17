#!/usr/bin/env bash
# nginx throughput: no tracer / bigram tracer / naive per-event tracer.
# Appends to data/bench.jsonl via bench.py. Container is left UNPINNED (matches the eval captures).
# usage: bash bench/run_nginx.sh [container] [runs]
set -u
C=${1:-demo}; RUNS=${2:-10}
cd "$(dirname "$0")/.."
sudo -v || exit 1
docker start "$C" >/dev/null
docker update --cpuset-cpus 0-3 "$C" >/dev/null
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

LOGF=""; DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  sudo -n pkill -9 -f "ebpf/tracer.py|ebpf/naive_tracer.py" 2>/dev/null
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted - cleaning up"; exit 130' INT TERM

tracer_pid() { pgrep -n -f "^python3 -u ebpf/"; }
start_tracer() {
  LOGF=$(mktemp)
  sudo -n python3 -u "$1" "$C" /tmp/_nginx_trace.csv < /dev/null > "$LOGF" 2>&1 &
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

echo "=== no tracer ===";          python3 bench.py nginx_off_bigram_session "$RUNS"
start_tracer ebpf/tracer.py in-kernel
echo "=== in-kernel (bigram) ==="; python3 bench.py nginx_in_kernel_bigram "$RUNS"
stop_tracer
start_tracer ebpf/naive_tracer.py naive
echo "=== naive per-event ===";    python3 bench.py nginx_naive_bigram_session "$RUNS"
stop_tracer

echo; echo "results appended to data/bench.jsonl"