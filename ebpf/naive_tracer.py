#!/usr/bin/env python3
"""
Strawman: per-event export to userspace, the conventional collection model.

Counts exported events AND events dropped by the perf ring buffer. Event loss
is the correctness argument: per-event export drops events under load, while
in-kernel aggregation cannot, by construction.

usage: sudo python3 ebpf/naive_tracer.py [container]
       prints "exported,lost,loss_pct" on exit
"""
from bcc import BPF
import os, signal, subprocess, sys

def cgroup_id_for(c):
    cid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Id}}", c], text=True).strip()
    return os.stat(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope").st_ino

container = sys.argv[1] if len(sys.argv) > 1 else "demo"
cgid = cgroup_id_for(container)

prog = r"""
struct evt { u64 ts; u32 pid; u32 nr; };
BPF_PERF_OUTPUT(events);

TRACEPOINT_PROBE(raw_syscalls, sys_enter) {
    if (bpf_get_current_cgroup_id() != TARGET_CGROUP)
        return 0;
    struct evt e = {};
    e.ts = bpf_ktime_get_ns();
    e.pid = bpf_get_current_pid_tgid() >> 32;
    e.nr = args->id;
    events.perf_submit(args, &e, sizeof(e));
    return 0;
}
"""

b = BPF(text=prog, cflags=[f"-DTARGET_CGROUP={cgid}ULL"])

n_events = 0
n_lost = 0

def on_event(cpu, data, size):
    global n_events
    e = b["events"].event(data)
    n_events += 1          # userspace does the counting, as Falco/ptrace do

def on_lost(lost):
    global n_lost
    n_lost += lost

b["events"].open_perf_buffer(on_event, page_cnt=64, lost_cb=on_lost)

# marker the orchestrator waits for before starting the workload
print(f"READY naive per-event tracer cgroup={cgid}", flush=True)

def report(*_):
    total = n_events + n_lost
    pct = (100.0 * n_lost / total) if total else 0.0
    print(f"\nRESULT exported={n_events} lost={n_lost} loss_pct={pct:.3f}",
          flush=True)
    sys.exit(0)

signal.signal(signal.SIGTERM, report)

try:
    while True:
        b.perf_buffer_poll()
except KeyboardInterrupt:
    report()