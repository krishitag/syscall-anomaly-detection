#!/usr/bin/env python3
"""
Container syscall tracer: in-kernel unigram + bigram aggregation,
sliding windows.

usage: sudo python3 ebpf/tracer.py <container> [out.csv]
"""
from bcc import BPF
import csv, json, os, subprocess, sys, time
from vocab import VOCAB_NAMES, NR_TO_INDEX

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "member2"))
import schema

TICK_NS = 1_000_000_000      # emit a row every 1 s
SPAN_TICKS = 2               # each row covers the last 2 s (sliding)
PAIRS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pairs.json")
SURVEY_FILE = "data/pair_survey.json"

def cgroup_id_for(container):
    cid = subprocess.check_output(
        ["docker", "inspect", "-f", "{{.Id}}", container], text=True).strip()
    return os.stat(f"/sys/fs/cgroup/system.slice/docker-{cid}.scope").st_ino

container = sys.argv[1] if len(sys.argv) > 1 else "demo"
cgid = cgroup_id_for(container)

# the 50 emitted pair columns, as (vocab_i, vocab_j); empty until surveyed
if os.path.exists(PAIRS_FILE):
    PAIRS = [tuple(p) for p in json.load(open(PAIRS_FILE))]
else:
    PAIRS = []
    print(f"WARNING: {PAIRS_FILE} missing - pair columns will be zero. "
          f"Run a survey capture, then pick_pairs.py")
PAIR_INDEX = {p: k for k, p in enumerate(PAIRS)}

prog = r"""
BPF_HASH(counts, u32, u64);
BPF_HASH(bigrams, u64, u64, 65536);
BPF_HASH(last_sc, u32, u32);

TRACEPOINT_PROBE(raw_syscalls, sys_enter) {
    if (bpf_get_current_cgroup_id() != TARGET_CGROUP)
        return 0;

    u32 nr = args->id;
    counts.increment(nr);

    u32 tid = (u32)bpf_get_current_pid_tgid();
    u32 *prev = last_sc.lookup(&tid);
    if (prev) {
        u64 key = ((u64)(*prev) << 32) | (u64)nr;
        bigrams.increment(key);
    }
    last_sc.update(&tid, &nr);
    return 0;
}
"""

b = BPF(text=prog, cflags=[f"-DTARGET_CGROUP={cgid}ULL"])
uni_map, big_map = b["counts"], b["bigrams"]
print(f"container={container} cgroup_id={cgid}  (Ctrl+C to stop)")

out_path = sys.argv[2] if len(sys.argv) > 2 else \
    f"data/{container}_{time.strftime('%Y%m%d_%H%M%S')}.csv"
os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
f = open(out_path, "w", newline="")
w = csv.writer(f, lineterminator="\n")
w.writerow(schema.ALL_COLUMNS)
print(f"writing {out_path}  (sliding {SPAN_TICKS}s window, {TICK_NS/1e9:g}s step)")

def snapshot():
    uni = {k.value: v.value for k, v in uni_map.items()}
    big = {}
    for k, v in big_map.items():
        prev_nr, curr_nr = k.value >> 32, k.value & 0xFFFFFFFF
        i, j = NR_TO_INDEX.get(prev_nr), NR_TO_INDEX.get(curr_nr)
        if i is not None and j is not None:          # both in vocab
            big[(i, j)] = big.get((i, j), 0) + v.value
    return uni, big

hist = []           # [(ts, uni, big)] - newest last
survey = {}         # vocab-pair -> total, for pick_pairs.py
tick = time.time_ns()
try:
    while True:
        time.sleep(max(0, (tick + TICK_NS - time.time_ns()) / 1e9))
        now = time.time_ns()
        uni, big = snapshot()
        hist.append((now, uni, big))
        if len(hist) > SPAN_TICKS + 1:
            hist.pop(0)
        tick = now

        for p, c in big.items():
            survey[p] = c                             # cumulative totals

        if len(hist) < SPAN_TICKS + 1:
            continue                                  # not enough history yet

        base_ts, base_uni, base_big = hist[0]

        vec = [0] * 20
        for nr, total in uni.items():
            i = NR_TO_INDEX.get(nr)
            if i is not None:
                vec[i] = total - base_uni.get(nr, 0)

        pairs = [0] * 50
        for p, total in big.items():
            k = PAIR_INDEX.get(p)
            if k is not None:
                pairs[k] = total - base_big.get(p, 0)

        stats = [0.0, 0.0, 0, sum(1 for c in vec if c)]
        w.writerow([cgid, base_ts, now] + vec + pairs + stats)
        f.flush()

        active = {VOCAB_NAMES[i]: c for i, c in enumerate(vec) if c}
        npair = sum(1 for c in pairs if c)
        print(f"[{base_ts}..{now}] pairs={npair} {active or 'idle'}")
except KeyboardInterrupt:
    pass
finally:
    f.close()
    os.makedirs("data", exist_ok=True)
    json.dump({f"{i},{j}": c for (i, j), c in survey.items()},
              open(SURVEY_FILE, "w"), indent=1)
    print(f"\npair survey -> {SURVEY_FILE} ({len(survey)} distinct vocab pairs)")