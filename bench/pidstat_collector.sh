#!/usr/bin/env bash
# Review 3: steady-state collector CPU/RSS via `pidstat -p <pid> 1`.
#
# Runs in the background ALONGSIDE bench/run_all.sh. It watches for whichever
# eBPF tracer process is currently attached and samples it at 1 Hz with pidstat
# for as long as that tracer lives, then waits for the next condition's tracer.
# This gives a per-interval (steady-state) figure, unlike run_all.sh's `ps %cpu`
# column, which is a lifetime average dominated by BCC startup.
#
# usage: bash bench/pidstat_collector.sh [outlog]
#   then, in another shell:
#   bash bench/run_all.sh demo 10 200000 baseline,in_kernel_unigram,in_kernel,naive_perevent
set -u
OUT=${1:-bench/pidstat_steadystate.log}
cd "$(dirname "$0")/.."
command -v pidstat >/dev/null || { echo "pidstat not found (install sysstat)"; exit 1; }
: > "$OUT"
echo "pidstat collector -> $OUT   (stop with: pkill -f pidstat_collector.sh)"

cur=""; PS=""
cleanup() { [ -n "$PS" ] && kill "$PS" 2>/dev/null; }
trap cleanup EXIT INT TERM

while true; do
  pid=$(pgrep -n -f "^python3 -u ebpf/(tracer|naive_tracer|tracer_unigram)\.py" 2>/dev/null || true)
  if [ -n "$pid" ] && [ "$pid" != "$cur" ]; then
    [ -n "$PS" ] && kill "$PS" 2>/dev/null
    cur=$pid
    cmd=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)
    echo "=== $(date +%T)  tracer pid=$pid  cmd=[$cmd] ===" >> "$OUT"
    pidstat -h -u -r -p "$pid" 1 >> "$OUT" 2>&1 &
    PS=$!
  fi
  if [ -n "$cur" ] && ! kill -0 "$cur" 2>/dev/null; then
    [ -n "$PS" ] && kill "$PS" 2>/dev/null
    echo "=== $(date +%T)  tracer pid=$cur exited ===" >> "$OUT"
    cur=""; PS=""
  fi
  sleep 1
done
