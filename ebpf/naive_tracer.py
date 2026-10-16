#!/usr/bin/env python3
"""Strawman: per-event export to userspace, the conventional collection model."""
from bcc import BPF
import os, subprocess, sys

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
n = 0
def cb(cpu, data, size):
    global n
    e = b["events"].event(data)
    n += 1          # userspace does the counting, as Falco/ptrace designs do
b["events"].open_perf_buffer(cb, page_cnt=64)
print(f"naive per-event tracer, cgroup={cgid} (Ctrl+C to stop)")
try:
    while True:
        b.perf_buffer_poll()
except KeyboardInterrupt:
    print(f"\n{n} events exported")