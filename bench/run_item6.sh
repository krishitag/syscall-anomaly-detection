#!/usr/bin/env bash
# Item 6 (Review 3): overhead under multi-container and heavy load.
# Hard cap 30 min. NO retry loops: a failed run is logged "FAILED" and skipped.
#
#  Multi-container : 3 nginx containers (demo, p17_nginx2, p17_nginx3), all
#                    unpinned. Untraced vs traced (one ebpf/tracer.py per
#                    container, CSV -> data/multi_<name>.csv). Driven by the
#                    nginx client (bench/bench_concurrent.py) at 1 connection
#                    for 60 s, 3 runs, all three containers at once.
#  Heavy load      : demo only, client at 50 connections for 60 s, 3 runs,
#                    untraced vs traced (ebpf/tracer.py).
#  Collector       : each tracer's %CPU and RSS via `ps`, sampled every 5 s.
#
# Raw output: /tmp/item6_results.log (throughput) and /tmp/item6_cpu.log (ps).
# usage: bash bench/run_item6.sh
set -u
cd "$(dirname "$0")/.."
DEADLINE=$(( $(date +%s) + 1800 ))      # 30 minutes
SECS=60
RUNS=3
C1=demo; C2=p17_nginx2; C3=p17_nginx3
ALL="$C1 $C2 $C3"
RES=/tmp/item6_results.log
CPU=/tmp/item6_cpu.log
: > "$RES"; : > "$CPU"

sudo -n true || exit 1
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

log() { echo "$*" | tee -a "$RES"; }
time_left() { [ "$(date +%s)" -lt "$DEADLINE" ]; }
tracer_pid_for() { pgrep -n -f "ebpf/tracer\.py $1 "; }

SAMPLER=""
start_sampler() {   # $1 = phase label; $2.. = pids
  local label=$1; shift; local pids="$*"
  ( while :; do
      ts=$(date +%s)
      for p in $pids; do
        set -- $(ps -o %cpu=,rss= -p "$p" 2>/dev/null)
        [ -n "${1:-}" ] && echo "$label,$ts,$p,$1,$2" >> "$CPU"
      done
      sleep 5
    done ) &
  SAMPLER=$!
}
stop_sampler() { [ -n "$SAMPLER" ] && kill "$SAMPLER" 2>/dev/null; SAMPLER=""; }

DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  stop_sampler
  pkill -f "bench_concurrent.py" 2>/dev/null
  sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null; sleep 1
  sudo -n pkill -9  -f "ebpf/tracer.py" 2>/dev/null
  for c in "$C2" "$C3"; do docker rm -f "$c" >/dev/null 2>&1 && echo "removed $c"; done
  docker update --cpuset-cpus 0-3 "$C1" >/dev/null 2>&1
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
}
trap cleanup EXIT
trap 'echo; echo "interrupted"; exit 130' INT TERM

# one client run against one container; echoes rps or FAILED to stdout
client() {   # $1 container, $2 conc
  local out; out=$(timeout $((SECS + 20)) python3 bench/bench_concurrent.py "$1" "$2" "$SECS" 2>/dev/null)
  local rps; rps=$(echo "$out" | grep -oE "rps=[ ]*[0-9.]+" | grep -oE "[0-9.]+" | head -1)
  echo "${rps:-FAILED}"
}

# drive all three containers at once at concurrency $1, label $2
drive_three() {   # $1 conc, $2 scenario label
  local conc=$1 label=$2 r
  for r in $(seq "$RUNS"); do
    time_left || { log "$label,run$r,SKIPPED_deadline"; continue; }
    local f1 f2 f3
    f1=$(mktemp); f2=$(mktemp); f3=$(mktemp)
    client "$C1" "$conc" > "$f1" &  p1=$!
    client "$C2" "$conc" > "$f2" &  p2=$!
    client "$C3" "$conc" > "$f3" &  p3=$!
    wait "$p1" "$p2" "$p3"
    log "$label,run$r,$C1,$(cat "$f1")"
    log "$label,run$r,$C2,$(cat "$f2")"
    log "$label,run$r,$C3,$(cat "$f3")"
    rm -f "$f1" "$f2" "$f3"
  done
}

echo "### item 6 start $(date +%T)  (deadline $(date -d @$DEADLINE +%T))"

# --- containers ---
docker start "$C1" >/dev/null
IMG=$(docker inspect -f '{{.Config.Image}}' "$C1" 2>/dev/null || echo nginx)
for c in "$C2" "$C3"; do
  docker inspect "$c" >/dev/null 2>&1 && docker rm -f "$c" >/dev/null 2>&1
  docker run -d --name "$c" "$IMG" >/dev/null && echo "created $c ($IMG)"
done
for c in $ALL; do docker update --cpuset-cpus 0-3 "$c" >/dev/null; done
sleep 2

# ================= MULTI-CONTAINER =================
echo "=== multi-container UNTRACED (conc=1, 60s, 3 runs) ==="
drive_three 1 multi_untraced

echo "=== multi-container: attaching one tracer per container ==="
declare -A TPID
for c in $ALL; do
  LOGF=$(mktemp)
  sudo -n python3 -u ebpf/tracer.py "$c" "data/multi_${c}.csv" < /dev/null > "$LOGF" 2>&1 &
  echo -n "  $c"; ok=0
  for _ in $(seq 60); do
    time_left || break
    grep -qE "READY|cgroup_id=" "$LOGF" 2>/dev/null && { ok=1; break; }
    sleep 1; echo -n "."
  done
  if [ "$ok" = 1 ]; then
    sleep 1; TPID[$c]=$(tracer_pid_for "$c")
    log "attach,$c,OK,pid=${TPID[$c]}"; echo " ok (pid ${TPID[$c]})"
  else
    log "attach,$c,FAILED"; echo " FAILED"; tail -3 "$LOGF"
  fi
done
echo "  tracers attached: $(pgrep -c -f '^python3 -u ebpf/tracer.py') (expect 3)"

echo "=== multi-container TRACED (conc=1, 60s, 3 runs) ==="
start_sampler multi_traced ${TPID[$C1]:-} ${TPID[$C2]:-} ${TPID[$C3]:-}
drive_three 1 multi_traced
stop_sampler
sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null; sleep 2
sudo -n pkill -9  -f "ebpf/tracer.py" 2>/dev/null; sleep 1
[ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json

# ================= HEAVY LOAD (demo only, conc=50) =================
echo "=== heavy-load UNTRACED (demo, conc=50, 60s, 3 runs) ==="
for r in $(seq "$RUNS"); do
  time_left || { log "heavy_untraced,run$r,SKIPPED_deadline"; continue; }
  log "heavy_untraced,run$r,$C1,$(client "$C1" 50)"
done

echo "=== heavy-load: attaching tracer on demo ==="
HPID=""
if time_left; then
  LOGF=$(mktemp)
  sudo -n python3 -u ebpf/tracer.py "$C1" /tmp/_item6_heavy.csv < /dev/null > "$LOGF" 2>&1 &
  ok=0; echo -n "  demo"
  for _ in $(seq 60); do time_left || break; grep -qE "READY|cgroup_id=" "$LOGF" 2>/dev/null && { ok=1; break; }; sleep 1; echo -n "."; done
  if [ "$ok" = 1 ]; then sleep 1; HPID=$(tracer_pid_for "$C1"); log "attach,heavy_demo,OK,pid=$HPID"; echo " ok (pid $HPID)"
  else log "attach,heavy_demo,FAILED"; echo " FAILED"; tail -3 "$LOGF"; fi
fi

echo "=== heavy-load TRACED (demo, conc=50, 60s, 3 runs) ==="
[ -n "$HPID" ] && start_sampler heavy_traced "$HPID"
for r in $(seq "$RUNS"); do
  time_left || { log "heavy_traced,run$r,SKIPPED_deadline"; continue; }
  log "heavy_traced,run$r,$C1,$(client "$C1" 50)"
done
stop_sampler

cleanup
echo "### item 6 done $(date +%T)"
echo "raw: $RES and $CPU"
