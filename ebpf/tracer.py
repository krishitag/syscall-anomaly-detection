from bcc import BPF
import os, subprocess, sys, time
from vocab import VOCAB_NAMES, NR_TO_INDEX

WINDOW_NS = 1_000_000_000  # 1 second

def cgroup_id_for(container):
    cid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Id}}", container], text=True).strip()
    return os.stat(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope").st_ino

container = sys.argv[1] if len(sys.argv) > 1 else "demo"
cgid = cgroup_id_for(container)

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
counts = b["counts"]
print(f"container={container} cgroup_id={cgid}  (Ctrl+C to stop)")

prev = {}
window_start = time.time_ns()
try:
    while True:
        # sleep until this window's end, without drifting
        time.sleep(max(0, (window_start + WINDOW_NS - time.time_ns()) / 1e9))
        window_end = time.time_ns()

        cur = {k.value: v.value for k, v in counts.items()}
        vec = [0] * 20
        for nr, total in cur.items():
            i = NR_TO_INDEX.get(nr)
            if i is not None:
                vec[i] = total - prev.get(nr, 0)
        prev = cur

        active = {VOCAB_NAMES[i]: c for i, c in enumerate(vec) if c}
        print(f"[{window_start}..{window_end}] {active or 'idle'}")
        window_start = window_end
except KeyboardInterrupt:
    pass