#!/usr/bin/env bash
# Review 3: overhead with THREE nginx containers, each traced by its own
# tracer, under a high-concurrency client (50 connections).
#
# Measures each container's throughput (bench/bench_concurrent.py, 50 conns)
#   (1) baseline: no tracers attached
#   (2) traced:   one ebpf/tracer.py per container, all three attached at once
# so the comparison shows the per-container cost while all three collectors run.
#
# Creates two extra containers (demo_m2, demo_m3); removes ONLY those on exit,
# never 'demo'. Leaves demo unpinned. Restores data/pair_survey.json, which
# each tracer rewrites on exit.
#
# usage: bash bench/run_multi.sh   (needs sudo for the tracers)
set -u
BASE=${1:-demo}
CONC=${CONC:-50}
DUR=${DUR:-15}
EXTRA="demo_m2 demo_m3"
ALL="$BASE $EXTRA"
cd "$(dirname "$0")/.."

sudo -n true || exit 1   # passwordless gate (sudo -v needs a tty under mixed sudoers rules)
IMG=$(docker inspect -f '{{.Config.Image}}' "$BASE" 2>/dev/null || echo nginx)
docker start "$BASE" >/dev/null
for c in $EXTRA; do
  if ! docker inspect "$c" >/dev/null 2>&1; then
    docker run -d --name "$c" "$IMG" >/dev/null && echo "created $c ($IMG)"
  else
    docker start "$c" >/dev/null
  fi
done
for c in $ALL; do docker update --cpuset-cpus 0-3 "$c" >/dev/null; done
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

declare -A LOGS
DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null; sleep 1
  sudo -n pkill -9  -f "ebpf/tracer.py" 2>/dev/null
  for c in $EXTRA; do docker rm -f "$c" >/dev/null 2>&1 && echo "removed $c"; done
  docker update --cpuset-cpus 0-3 "$BASE" >/dev/null 2>&1
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted - cleaning up"; exit 130' INT TERM

echo "=== (1) BASELINE: no tracers, ${CONC} concurrent connections ==="
for c in $ALL; do python3 bench/bench_concurrent.py "$c" "$CONC" "$DUR"; done

echo; echo "=== attaching one tracer per container ==="
for c in $ALL; do
  LOGF=$(mktemp); LOGS[$c]=$LOGF
  sudo -n python3 -u ebpf/tracer.py "$c" "/tmp/_multi_${c}.csv" < /dev/null > "$LOGF" 2>&1 &
  echo -n "  $c"
  ok=0
  for _ in $(seq 90); do
    grep -qE "READY|cgroup_id=" "$LOGF" 2>/dev/null && { echo " ok"; ok=1; break; }
    sleep 1; echo -n "."
  done
  [ "$ok" = 1 ] || { echo " FAILED"; tail -5 "$LOGF"; exit 1; }
done
sleep 3
echo "  tracers attached: $(pgrep -c -f '^python3 -u ebpf/tracer.py') (expect 3)"

echo; echo "=== (2) TRACED: 3 tracers attached, ${CONC} concurrent connections ==="
for c in $ALL; do python3 bench/bench_concurrent.py "$c" "$CONC" "$DUR"; done

cleanup
echo; echo "done."
