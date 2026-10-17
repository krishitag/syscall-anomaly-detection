#!/usr/bin/env bash
# One-terminal demo: tracer + traffic in the background, watcher in front.
# Ctrl+C once stops everything.
# usage: bash demo/run_demo.sh [container] [traffic_seconds]
set -u
C=${1:-demo}; DUR=${2:-600}
cd "$(dirname "$0")/.."

docker start "$C" >/dev/null
sudo -v || exit 1
mkdir -p data
rm -f data/live.csv
[ -f data/pair_survey.json ] && cp data/pair_survey.json /tmp/pair_survey.bak

DONE=0
cleanup() {
  [ "$DONE" = 1 ] && return; DONE=1
  stty sane 2>/dev/null
  echo; echo "stopping demo..."
  pkill -f "demo/watch.py"     2>/dev/null
  pkill -f "normal_traffic.py" 2>/dev/null
  sudo -n pkill -INT -f "ebpf/tracer.py" 2>/dev/null   # polite: lets it close the CSV
  sleep 1
  sudo -n pkill -9 -f "ebpf/tracer.py" 2>/dev/null     # then force
  [ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
  echo "demo stopped."
}
trap cleanup EXIT
trap 'exit 130' INT TERM

sudo -n python3 -u ebpf/tracer.py "$C" data/live.csv \
  < /dev/null > /tmp/demo_tracer.log 2>&1 &
python3 workload/normal_traffic.py "$C" "$DUR" 7 \
  < /dev/null > /tmp/demo_traffic.log 2>&1 &

echo "starting tracer (BCC compile takes ~10 s)..."
python3 demo/watch.py data/live.csv