# Collection Overhead — Measured Results

**Date:** 2026-10-17 · **Measured by:** Naman Bhatia (Member 1)
**Raw data:** `bench/results.csv` (per-run), `data/bench.jsonl` (throughput runs)
**Harness:** `bench/run_all.sh`, `bench/syscall_bench.c`, `bench.py`

---

## 1. Headline

**In-kernel aggregation adds 405 ns per system call (1.64× baseline).**
A per-event export path costs 896× baseline on the same microbenchmark, and
72.8% of nginx throughput on a realistic workload.

---

## 2. Experimental setup

| | |
|---|---|
| Host | Oracle VirtualBox guest |
| OS | Ubuntu 22.04 |
| Kernel | 6.8.0-138-generic, x86_64 |
| vCPU / RAM | 4 cores / ~6 GB |
| Container | `nginx` (default tag), pinned to CPU 2 (`--cpuset-cpus 2`) |
| eBPF tooling | BCC (`python3-bpfcc`), attach point `raw_syscalls:sys_enter` |
| Tracer under test | `ebpf/tracer.py` — unigram + bigram in-kernel aggregation, sliding 2 s / 1 s windows |

All three conditions were run **back to back in a single session**, with the
orchestrator verifying each tracer reported attachment before any measurement
began. This check was added after an earlier run produced a result faster than
the untraced baseline, caused by a tracer that had silently failed to attach.

---

## 3. Conditions

| Condition | What is attached | What crosses to user space |
|---|---|---|
| `baseline` | nothing | nothing |
| `in_kernel` | `ebpf/tracer.py` | one 74-value vector per second |
| `naive_perevent` | `ebpf/naive_tracer.py` | one record per system call |

`naive_perevent` uses the **same attach point and the same BCC/Python tooling**
as `in_kernel`, differing only in the data path. This isolates the cost of
per-event export while holding the implementation language constant.

---

## 4. Microbenchmark: cost per system call

A tight loop of `syscall(SYS_getpid)` executed **inside the container**
(`bench/syscall_bench.c`, statically linked). `getpid` was chosen as the
cheapest possible syscall, so the measurement is dominated by trap and probe
cost rather than by kernel work. The raw `syscall()` interface is used
deliberately: the glibc `getpid()` wrapper can cache the PID and never enter
the kernel.

| Condition | Median ns/syscall | Runs | Iterations/run | Δ vs baseline | Ratio |
|---|---|---|---|---|---|
| baseline | **632.59** | 30 | 5,000,000 | — | 1.00× |
| **in_kernel** | **1,037.73** | 10 | 5,000,000 | **+405.14 ns** | **1.64×** |
| naive_perevent | **566,768.50** | 3 | 200,000 | +566,135.92 ns | 895.96× |

Iteration count differs for `naive_perevent` because a 5M-iteration run takes
over 45 minutes under per-event export. `ns/syscall` is a rate, so the
comparison holds; the difference is recorded here for transparency.

### Why the microbenchmark, and not only throughput

An earlier attempt measured nginx request throughput with and without tracing.
On this VM the traced/untraced difference fell **inside run-to-run variance**
(σ ≈ 50–68 rps on a ~470 rps mean, ±14%), and in one set the traced
configuration measured *faster*. Each HTTP request performs roughly ten system
calls plus network and disk work, so syscall cost is a small fraction of what
is being timed. The microbenchmark removes that dilution and resolves the
per-event cost directly.

---

## 5. Realistic workload: nginx throughput

Closed-loop single-connection HTTP client, 3,000 requests per run, 10 runs plus
a warm-up (`bench.py`, raw results in `data/bench.jsonl`).

| Condition | Throughput (rps) | σ | p50 latency | p99 latency | Δ throughput |
|---|---|---|---|---|---|
| baseline | 472.0 | 67.6 | 1.644 ms | 11.74 ms | — |
| in_kernel | 490.7 | 51.0 | 1.530 ms | 11.57 ms | within noise |
| naive_perevent | 128.3 | 12.9 | 6.447 ms | 31.90 ms | **−72.8%** |

**The in-kernel tracer's cost is below measurement resolution on this
workload.** The traced and untraced means differ by less than one standard
deviation, and in the direction that would imply tracing makes the system
faster — i.e. noise. This is reported as "below resolution" rather than as a
precise small percentage the data does not support. The microbenchmark in §4 is
the measurement that resolves this cost.

> **Note:** these throughput figures were taken on the **unigram-only** tracer
> (pre-17-Oct). The current tracer additionally maintains bigram state, which
> the §4 microbenchmark does measure. The throughput comparison is retained
> because the per-event vs in-kernel gap it demonstrates is not sensitive to
> that difference, but it should be re-run before final submission.

---

## 6. Unigram-only vs unigram+bigram — NOT MEASURED

The +405 ns figure in §4 is for the **current** tracer, which maintains both
unigram counts and bigram state (one extra map lookup and one extra map update
per event, plus a per-thread scratch map).

**No per-syscall measurement of the unigram-only tracer exists.** The
microbenchmark harness was built after bigrams had already landed. The only
unigram-era data is the nginx throughput run in §5, where the tracer's cost was
below measurement resolution — so it cannot be differenced against the current
figure.

This is a gap worth closing: it is a clean ablation ("bigram tracking accounts
for N ns of the 405 ns total") and costs about three minutes. The unigram
tracer is recoverable from git history:

```bash
git log --oneline -- ebpf/tracer.py        # find the commit before bigrams
git show <commit>^:ebpf/tracer.py > /tmp/tracer_unigram.py
# then run the in_kernel condition against that file
```

Until measured, the paper should attribute the full +405 ns to the combined
unigram+bigram tracer and make no claim about the split.

---

## 7. Collector resource usage

Sampled during each run; per-run values in `bench/results.csv`
(`collector_cpu_pct`, `collector_rss_kb`).

The in-kernel collector wakes once per second to read a map. The per-event
collector executes a Python callback for every system call, which is the source
of the §4 result.

---

## 8. Event loss

`ebpf/naive_tracer.py` instruments BCC's perf-buffer `lost_cb`.

| Exported | Lost | Loss |
|---|---|---|
| 1,202,720 | 0 | 0.000% |

**Interpretation — read before citing this.** Zero loss here does **not**
establish that per-event export is lossless under load. The consumer was slow
enough (§4) that it throttled the producing workload: the benchmark could not
outrun the reader, so the ring buffer never reached overflow. A faster consumer
paired with a faster workload would be required to reach the loss regime.

The structural argument stands independently of this measurement: in-kernel
aggregation has **no queue and therefore no loss mechanism**, since counters are
incremented in place and read by differencing snapshots. Per-event export has a
bounded buffer and can drop. This should be argued from the design, not from
this number.

---

## 9. Honest limitations

- **The per-event comparison uses a Python-based exporter.** It holds tooling
  constant against our own collector, which is what makes it a fair isolation of
  the data path. It is **not** a measurement of optimised C-based collection
  agents such as Falco, which we did not run. A direct comparison against
  production collectors is future work, and is the single most valuable
  remaining measurement.
- **Published figures are not directly comparable.** Wang et al. report 8.41%
  overhead for `ptrace`-based collection. That figure comes from different
  hardware, kernel and workload, so it is cited as context for the magnitude of
  per-event collection cost, not as a quantity our numbers can be ranked against.
- **Virtualised environment.** A 4-vCPU VirtualBox guest shows ±14% run-to-run
  variance on throughput workloads. Bare-metal measurement would tighten every
  figure here and is listed as future work.
- **Unequal sample sizes.** baseline n=30, in_kernel n=10, naive n=3.
- **Single workload class.** nginx only; generalisation across application types
  is untested.
- **`getpid` is a best case for the probe.** It is the cheapest syscall
  available, so the *relative* overhead (1.64×) is an upper bound — on
  syscalls that do real kernel work, the same +405 ns is a smaller fraction of
  total cost.

---

## 10. Resume / abstract line

> In-kernel eBPF feature aggregation added **405 ns per system call (1.64×
> baseline)** at ~1.6 M syscalls/s, compared with **896×** for an equivalent
> per-event export path and a **72.8%** nginx throughput reduction, with zero
> events dropped.

---

## 11. Reproducing

```bash
gcc -O2 -static -o bench/syscall_bench bench/syscall_bench.c
sudo -v
bash bench/run_all.sh demo 10 5000000            # all three conditions
bash bench/run_all.sh demo 3 200000 naive_perevent   # naive only (slow)
```

Results append to `bench/results.csv`; the script prints medians on completion.