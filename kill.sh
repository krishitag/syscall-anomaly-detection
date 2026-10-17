#!/usr/bin/env bash
# Kill everything any of the demo/bench scripts start. Safe to run anytime.
# usage: bash kill.sh
cd "$(dirname "$0")"

pkill -f "run_demo.sh|run_all.sh|run_nginx.sh|window_stats.sh|attack.sh" 2>/dev/null
pkill -f "demo/watch.py|normal_traffic.py|bench.py" 2>/dev/null
sudo pkill -INT -f "ebpf/tracer.py|ebpf/tracer_unigram.py|ebpf/naive_tracer.py" 2>/dev/null
sleep 1
sudo pkill -9 -f "ebpf/tracer.py|ebpf/tracer_unigram.py|ebpf/naive_tracer.py|syscall_bench" 2>/dev/null
pkill -9 -f "run_demo.sh|run_all.sh|run_nginx.sh|window_stats.sh|demo/watch.py|normal_traffic.py|bench.py" 2>/dev/null

docker update --cpuset-cpus 0-3 demo >/dev/null 2>&1
[ -f /tmp/pair_survey.bak ] && cp /tmp/pair_survey.bak data/pair_survey.json
stty sane 2>/dev/null

pgrep -af "watch.py|normal_traffic|tracer|syscall_bench|run_all|run_nginx|run_demo|window_stats" \
  && echo "^^ still alive" || echo "ALL DEAD"