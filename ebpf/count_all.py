from bcc import BPF
import time

prog = r"""
BPF_HASH(counts, u32, u64);

TRACEPOINT_PROBE(raw_syscalls, sys_enter) {
    u32 nr = args->id;
    counts.increment(nr);
    return 0;
}
"""

b = BPF(text=prog)
print("Tracing all syscalls... Ctrl+C to stop")

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