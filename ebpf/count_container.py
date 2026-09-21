from bcc import BPF
import os, subprocess, sys, time

def cgroup_id_for(container):
    cid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Id}}", container], text=True).strip()
    path = f"/sys/fs/cgroup/system.slice/docker-{cid}.scope"
    return os.stat(path).st_ino

container = sys.argv[1] if len(sys.argv) > 1 else "demo"
cgid = cgroup_id_for(container)
print(f"container={container} cgroup_id={cgid}")

prog = r"""
BPF_HASH(counts, u32, u64);

TRACEPOINT_PROBE(raw_syscalls, sys_enter) {
    if (bpf_get_current_cgroup_id() != TARGET_CGROUP)
        return 0;
    u32 nr = args->id;
    counts.increment(nr);
    return 0;
}
"""

b = BPF(text=prog, cflags=[f"-DTARGET_CGROUP={cgid}ULL"])
print("Tracing... Ctrl+C to stop")

try:
    while True:
        time.sleep(2)
        top = sorted(b["counts"].items(),
                     key=lambda kv: kv[1].value, reverse=True)[:10]
        print("--- top 10 ---")
        for k, v in top:
            print(f"syscall {k.value:4d}: {v.value}")
except KeyboardInterrupt:
    pass