#!/usr/bin/env bash
# Simulated post-exploitation attacks against the demo container.
# Logs each attack's start/end (epoch ns) so capture windows can be labelled.
# usage: bash workload/attack.sh [container]
set -u
C=${1:-demo}
GAP=${GAP:-15}
LOG=${LOG:-data/attack_log.csv}
mkdir -p "$(dirname "$LOG")"
echo "attack,start_ns,end_ns" > "$LOG"

run() {
  local name=$1; shift
  local s; s=$(date +%s%N)
  "$@" >/dev/null 2>&1 || true
  local e; e=$(date +%s%N)
  echo "$name,$s,$e" >> "$LOG"
  echo "[$(date +%T)] $name"
  sleep "$GAP"
}

sleep "$GAP"
run recon         docker exec "$C" sh -c 'id; uname -a; cat /etc/passwd; ls -la /; kill -0 1'
run drop_exec     docker exec "$C" sh -c 'cp /bin/ls /tmp/.x && chmod +x /tmp/.x && chown nobody /tmp/.x && /tmp/.x / && rm /tmp/.x'
run outbound_conn docker exec "$C" bash -c 'exec 3<>/dev/tcp/172.17.0.1/4444'
run ns_escape     docker exec "$C" sh -c 'unshare --user --map-root-user true'
run spawn_storm   docker exec "$C" sh -c 'for i in $(seq 50); do sh -c true; done'
echo "done. log: $LOG"