# Collection Overhead — Measured Results

**Last updated:** 2026-10-17 (evening session) · **Measured by:** Naman Bhatia (Member 1)
**Raw data:** `bench/results.csv` (microbenchmark, current session), `bench/results_old.csv`
(morning session), `data/bench.jsonl` (nginx throughput, all sessions), `bench/window_stats.log`
**Harness:** `bench/run_all.sh`, `bench/syscall_bench.c`, `bench/run_nginx.sh`, `bench.py`,
`bench/window_stats.sh`

---

## 1. Headline

- **The current tracer (unigram + bigram) adds 356 ns per system call (1.70× baseline).**
  The unigram-only tracer adds 220 ns (1.44×), so **bigram tracking accounts for about 136 ns,
  roughly 38% of the tracer's cost.**
- **Per-event export costs 73.4% of nginx throughput** (3.76× slowdown, 4.0× p50 latency) and
  **~896× per syscall** on the microbenchmark.
- **On nginx, the in-kernel tracer's cost is below measurement resolution**, in two separate
  sessions and on both tracer versions. The microbenchmark is what resolves it.

---

## 2. Experimental setup

| | |
|---|---|
| Host | Oracle VirtualBox guest |
| OS | Ubuntu 22.04 |
| Kernel | 6.8.0-138-generic, x86_64 |
| vCPU / RAM | 4 cores / ~6 GB |
| Container | `nginx` (default tag) |
| CPU placement | **Microbenchmark:** container pinned to CPU 2 (`--cpuset-cpus 2`), unpinned afterwards. **nginx throughput and window stats:** unpinned (all 4 cores), matching the training and evaluation captures |
| eBPF tooling | BCC (`python3-bpfcc`), attach point `raw_syscalls:sys_enter` |
| Tracers under test | `ebpf/tracer.py` (unigram + bigram, sliding 2 s / 1 s windows); `ebpf/tracer_unigram.py` (unigram only, from commit `879595a`); `ebpf/naive_tracer.py` (per-event export) |

Every traced condition waits for the tracer to report attachment before measuring. This check
was added after an earlier run measured *faster* than the untraced baseline because the tracer
had silently failed to attach (the 1022 rps line kept in `data/bench.jsonl`, excluded from all
results).

---

## 3. Conditions

| Condition | What is attached | What crosses to user space |
|---|---|---|
| `baseline` | nothing | nothing |
| `in_kernel_unigram` | `ebpf/tracer_unigram.py` | one 20-count vector per second |
| `in_kernel` | `ebpf/tracer.py` | one 74-value vector per second |
| `naive_perevent` | `ebpf/naive_tracer.py` | one record per system call |

`naive_perevent` uses the **same attach point and the same BCC/Python tooling** as the in-kernel
tracers and differs only in the data path. This isolates the cost of per-event export while
holding the implementation language constant.

---

## 4. Microbenchmark: cost per system call

A tight loop of `syscall(SYS_getpid)` run **inside the container** (`bench/syscall_bench.c`,
statically linked). `getpid` is the cheapest syscall available, so the measurement is dominated
by trap and probe cost. The raw `syscall()` interface is used because glibc's `getpid()` wrapper
can cache the PID and never enter the kernel.

### Session B — evening (current; `bench/results.csv`)

All three conditions in one session, 10 runs × 5,000,000 iterations each.

| Condition | Median ns/syscall | Δ vs baseline | Ratio |
|---|---|---|---|
| baseline | **505.25** | — | 1.00× |
| in_kernel_unigram | **725.39** | **+220.14 ns** | 1.44× |
| **in_kernel** (unigram + bigram) | **861.07** | **+355.81 ns** | **1.70×** |

Run ranges: baseline 423–553, unigram 617–797, bigram 685–977 ns.

### Session A — morning (`bench/results_old.csv`)

| Condition | Median ns/syscall | Runs × iterations | Δ vs baseline | Ratio |
|---|---|---|---|---|
| baseline | 632.59 | 30 × 5M | — | 1.00× |
| in_kernel (unigram + bigram) | 1,037.73 | 10 × 5M | +405.14 ns | 1.64× |
| naive_perevent | 566,768.50 | 3 × 200k | +566,135.92 ns | 895.96× |

The naive condition used 200k iterations because a 5M-iteration run takes over 45 minutes under
per-event export. ns/syscall is a rate, so the comparison holds. The collector CPU/RSS columns
in this file are **invalid** (they measured the `sudo` wrapper; see §7).

### Reading the two sessions together

The bigram tracer's overhead was +405 ns in session A and +356 ns in session B, about 12% apart.
That's within this VM's session-to-session variation. Absolute baselines also moved (633 vs
505 ns), which is why every ratio here is computed **within a session**, never across sessions.

---

## 5. Ablation: unigram-only vs unigram + bigram

From session B (same session, same baseline):

| | ns added per syscall | Share of tracer cost |
|---|---|---|
| Unigram counting (cgroup filter + 1 map increment) | ~220 | ~62% |
| Bigram tracking (scratch-map lookup + update + pair increment) | ~136 | ~38% |
| **Total** | **~356** | 100% |

The run ranges of the two tracers overlap (617–797 vs 685–977 ns), so the ~136 ns split is an
estimate from medians, not a precise decomposition. Report it as approximate.

---

## 6. Realistic workload: nginx throughput

Closed-loop single-connection HTTP client, 3,000 requests per run, 10 runs plus a warm-up
(`bench.py`; raw results in `data/bench.jsonl`). Container unpinned.

### Session B — bigram tracer (current)

| Condition | rps | σ | p50 | p99 | Δ throughput |
|---|---|---|---|---|---|
| no tracer | 508.2 | 97.2 | 1.533 ms | 11.16 ms | — |
| in-kernel (bigram) | 534.8 | 145.5 | 1.509 ms | 10.22 ms | within noise |
| naive per-event | 135.1 | 12.9 | 6.168 ms | 30.22 ms | **−73.4%** |

### Session A — unigram tracer

| Condition | rps | σ | p50 | p99 | Δ throughput |
|---|---|---|---|---|---|
| no tracer | 472.0 | 67.6 | 1.644 ms | 11.74 ms | — |
| in-kernel (unigram) | 490.7 | 51.0 | 1.530 ms | 11.57 ms | within noise |
| naive per-event | 128.3 | 12.9 | 6.447 ms | 31.90 ms | −72.8% |

**Per-event export:** −73.4% / −72.8% throughput across the two sessions and both tracer
versions, with p50 latency 4.0× / 3.9× higher. Highly consistent.

**In-kernel tracer: below measurement resolution, replicated.** In both sessions the traced mean
came out slightly *higher* than the untraced one, with σ of 51–145 rps. That's noise, so it's
reported as "below resolution" rather than as a percentage. Each HTTP request performs roughly
ten syscalls plus network and disk work, so a ~356 ns per-syscall cost is a few microseconds per
~1.5 ms request — well under the VM's ±14–29% run-to-run variation. The microbenchmark (§4) is
the measurement that resolves it.

---

## 7. Collector resource usage

Sampled during each session-B run from the tracer's Python process (`collector_cpu_pct`,
`collector_rss_kb` in `bench/results.csv`).

| Tracer | CPU (`ps %cpu`) | RSS |
|---|---|---|
| in_kernel_unigram | 16.6% → 3.2% over 10 runs (median 5.5%) | ~112.4 MB |
| in_kernel | 18.7% → 3.2% over 10 runs (median 5.2%) | ~112.8 MB |

**How to read these — do not cite "5% CPU" or "112 MB" without this context:**

- **CPU.** `ps %cpu` is lifetime CPU time divided by elapsed time, so it's dominated by the BCC
  compile at startup and decays steadily (18.7% → 3.2%). Steady-state poller cost is below 3%
  and still falling at the end of the run. A per-interval measurement (`pidstat -p <pid> 1`) is
  needed for a steady-state figure.
- **RSS.** Almost all of the ~112 MB is BCC's embedded LLVM/clang toolchain loaded into the
  Python process, not the collection design. The BPF maps themselves are a few KB (§8). A
  libbpf/CO-RE build of the same tracer would sit at a few MB.
- **Where the in-kernel work is charged.** The BPF program runs in the context of the traced
  process, so its cost lands on the container (that's what §4 measures), not on the collector.
  Collector CPU covers only the once-per-second poller.

Session-A collector columns (`bench/results_old.csv`) measured the `sudo` wrapper rather than
the tracer and are invalid.

---

## 8. Window statistics and map read size

From `bench/window_stats.sh` (`bench/window_stats.log`): 119 windows of 2 s each, nginx traffic
with the 5 simulated attacks mixed in, bigram tracer, container unpinned.

| Metric (per 2 s window) | mean | median | max |
|---|---|---|---|
| Distinct syscall numbers (any, non-idle windows) | 17.1 | 12 | 77 |
| Total syscalls (any, non-idle windows) | 626.4 | 544 | 4,214 |
| Unigram map entries per read | 64.1 | 83 | 88 |
| Bigram map entries per read | 233.1 | 293 | 352 |

### What a read costs

- **Bounded size.** At most 88 unigram entries × 12 B (u32 key + u64 value) plus 352 bigram
  entries × 16 B (u64 key + u64 value) ≈ **6.7 KB per read**, once per second. Counters are never
  cleared, so entry counts plateau at the number of distinct syscalls and transitions ever seen.
  Read size does not grow with syscall rate.
- **Per-event export grows linearly.** At 16 B per event: ~4.4 KB/s at the median rate
  (272 syscalls/s), ~34 KB/s at the peak (2,107 syscalls/s).
- **So the byte advantage is rate-dependent.** The crossover is around **420 syscalls/s**. Below
  it, per-event export moves about as many bytes as the map read. The in-kernel design's
  advantage at nginx's moderate request rate is **the number of kernel→user crossings and
  per-event callbacks**, not bytes — which is exactly what the microbenchmark's 896× captures.
  The byte advantage appears only at high syscall rates. Do not claim "less data" unqualified.
- **The read itself is not free.** BCC's `.items()` walks the map with roughly two `bpf()` calls
  per entry, ~880 syscalls per read at the plateau. `BPF_MAP_LOOKUP_BATCH` would reduce this
  substantially (future work).

### Vocabulary evidence

Normal nginx traffic touches a **median of 12 distinct syscalls** per window, so the 20-slot
vocabulary covers normal behaviour well. But **88 distinct syscall numbers** appeared over the
run, and attack windows reached **77**. This supports extending the vocabulary for the final
review.

---

## 9. Event loss

`ebpf/naive_tracer.py` instruments BCC's perf-buffer `lost_cb` (session A).

| Exported | Lost | Loss |
|---|---|---|
| 1,202,720 | 0 | 0.000% |

**Zero loss here does not show that per-event export is lossless under load.** The consumer was
slow enough (§4) to throttle the producing workload, so the ring buffer never reached overflow.
Reaching the loss regime needs a faster consumer paired with a faster workload (future work).

The structural argument stands on the design: in-kernel aggregation has **no queue and therefore
no loss mechanism**, since counters are incremented in place and read by differencing snapshots.
Per-event export has a bounded buffer and can drop. Argue it from the design, not from this
number.

---

## 10. Limitations

- **The per-event comparison uses a Python-based exporter.** It holds tooling constant against
  our own collector, which is what makes it a fair isolation of the data path. It is **not** a
  measurement of optimised C-based agents such as Falco, which were not run. A direct comparison
  against a production collector is future work and the most valuable remaining measurement.
- **Published figures are not directly comparable.** Wang et al. report 8.41% overhead for
  `ptrace`-based collection on different hardware, kernel and workload. Cite it as context for
  the magnitude of per-event cost, not as something to rank against.
- **Virtualised environment.** The 4-vCPU VirtualBox guest varies ±14–29% run to run on nginx
  and ~12% session to session on the microbenchmark. Bare-metal measurement is future work.
- **`getpid` is a best case for the probe.** Relative overhead (1.70×) is an upper bound: on
  syscalls that do real kernel work, the same ~356 ns is a smaller fraction of total cost.
- **Unequal samples across sessions.** Session A baseline n=30, naive n=3; session B n=10 each.
- **Single workload class.** nginx only.
- **Collector RSS reflects BCC, not the design** (§7).

---

## 11. Abstract / resume line

> In-kernel eBPF feature aggregation added **~356 ns per system call (1.70× baseline on a
> `getpid` loop)**, of which bigram tracking accounts for ~136 ns. An equivalent per-event export
> path cost **~896× per syscall** and reduced nginx throughput by **73.4%**, while the in-kernel
> tracer's effect on nginx throughput was below measurement resolution across two sessions.

---

## 12. Reproducing

```bash
gcc -O2 -static -o bench/syscall_bench bench/syscall_bench.c
git show 879595a:ebpf/tracer.py > ebpf/tracer_unigram.py

bash bench/run_all.sh                                # baseline, unigram, bigram  (~6 min)
bash bench/run_all.sh demo 3 200000 naive_perevent   # naive per-event            (~8 min)
bash bench/run_nginx.sh                              # nginx, 3 conditions        (~7 min)
bash bench/window_stats.sh                           # window stats + map sizes   (~2.5 min)
```

Microbenchmark results append to `bench/results.csv`; nginx results append to `data/bench.jsonl`.
If anything hangs, `bash kill.sh` stops every script and tracer and unpins the container.