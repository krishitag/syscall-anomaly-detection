from bcc import BPF
import csv, os, subprocess, sys, time
from vocab import VOCAB_NAMES, NR_TO_INDEX

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "member2"))
import schema  # Krishita's column contract - single source of truth

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

out_path = sys.argv[2] if len(sys.argv) > 2 else \
    f"data/{container}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
f = open(out_path, "w", newline="")
w = csv.writer(f, lineterminator="\n")
w.writerow(schema.ALL_COLUMNS)
print(f"writing {out_path}")

prev = {}
window_start = time.time_ns()
try:
    while True:
        time.sleep(max(0, (window_start + WINDOW_NS - time.time_ns()) / 1e9))
        window_end = time.time_ns()

        cur = {k.value: v.value for k, v in counts.items()}
        vec = [0] * 20
        for nr, total in cur.items():
            i = NR_TO_INDEX.get(nr)
            if i is not None:
                vec[i] = total - prev.get(nr, 0)
        prev = cur

        stats = [0.0, 0.0, 0, sum(1 for c in vec if c)]
        w.writerow([cgid, window_start, window_end] + vec + [0] * 50 + stats)
        f.flush()

        active = {VOCAB_NAMES[i]: c for i, c in enumerate(vec) if c}
        print(f"[{window_start}..{window_end}] {active or 'idle'}")
        window_start = window_end
except KeyboardInterrupt:
    pass
finally:
    f.close()