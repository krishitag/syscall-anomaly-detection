# Review 3 — reproduction results

Numbers gathered while answering the Review-3 comments. Each section records the
exact command run and the exact figures it produced. Appended in task order.

Environment: Ubuntu 22.04 VirtualBox guest, kernel 6.8.0-138-generic, x86_64,
4 vCPU / ~6 GB RAM, Docker (cgroup v2), BCC `python3-bpfcc`. Demo container
`demo` = nginx, bridge IP 172.18.0.2, host gateway 172.18.0.1.

---

## 1. BCC version

Command:

```
dpkg -l | grep -i bpfcc
```

Result:

| Package | Version |
|---|---|
| bpfcc-tools | 0.18.0+ds-2 |
| libbpfcc | 0.18.0+ds-2 |
| python3-bpfcc | 0.18.0+ds-2 |

**BCC 0.18.0** (Ubuntu package `0.18.0+ds-2`). This is the version used for every
tracer measurement in the paper.

---

## 2. Extended attack workload

`workload/attack.sh`: the original 5 attacks (recon, drop_exec, outbound_conn,
ns_escape, spawn_storm) are kept first and unchanged. Four more were appended,
each run via `docker exec` through the same `run()` helper (so each gets the
same `timeout 5` and is logged to the attack CSV):

| Attack | What it does |
|---|---|
| `cred_harvest` | `cat /etc/shadow; cat /etc/passwd; env` |
| `html_drop` | write then delete `/usr/share/nginx/html/.x` |
| `cpu_burn` | 3 s busy loop (`while date +%s < end`) |
| `port_scan` | bash `/dev/tcp` scan of 10 ports on **172.18.0.1** (the demo container's real host gateway; 172.17.0.1 has no route from the container's 172.18.0.0/16 subnet) |

Smoke test (direct `docker exec`, same commands, tracer not attached):

```
cred_harvest : /etc/shadow readable (root:*:...), /etc/passwd + env printed
html_drop    : wrote-and-removed, exit 0
cpu_burn     : elapsed 2.73 s  (inside the 5 s timeout)
port_scan    : elapsed 0.38 s, port 22 reported open on the host gateway
```

All four complete well within the 5 s timeout. `bash -n workload/attack.sh` passes.

---

## 4. Confusion matrices: autoencoder vs security-family rule

Script: `bench/eval_confusion.py` (reuses `member2.evaluation_labels` for the
same overlap-based window labels the pipeline uses, and `person3_ml.detect` for
the autoencoder). The rule flags any window with a non-zero count in any of
execve, clone, connect, socket, setns, unshare, ptrace, fchmodat, fchownat, kill
(columns syscall_08/10/11/13/14/15/16/17/18/19).

Run: `python3 bench/eval_confusion.py`

### data/eval.csv (189 windows, 15 attack, 174 normal; threshold 0.0182547)

| Detector | TP | FP | TN | FN | Precision | Recall | F1 | FPR |
|---|---|---|---|---|---|---|---|---|
| Autoencoder | 10 | 0 | 174 | 5 | 1.0000 | 0.6667 | 0.8000 | 0.0000 |
| Security-rule | 10 | 0 | 174 | 5 | 1.0000 | 0.6667 | 0.8000 | 0.0000 |

The autoencoder figures reproduce `results.md` exactly (TP 10 / FP 0 / TN 174 /
FN 5). On this capture the naive security-family rule **matches the autoencoder
exactly** — normal nginx windows never fire those families, and the 5 missed
attack windows (mostly the hung `outbound_conn` connection) carry no
security-family syscall either, so both detectors miss the same 5.

Per-attack (detected / detection delay), both detectors identical here:

| Attack | windows | autoencoder | delay | rule | delay |
|---|---|---|---|---|---|
| recon | 2 | HIT | 0.76 s | HIT | 0.76 s |
| drop_exec | 2 | HIT | 1.01 s | HIT | 1.01 s |
| outbound_conn | 7 | HIT | 0.53 s | HIT | 0.53 s |
| ns_escape | 2 | HIT | 0.97 s | HIT | 0.97 s |
| spawn_storm | 2 | HIT | 0.66 s | HIT | 0.66 s |

Attacks detected: autoencoder 5/5, rule 5/5. Delays match `analyze.py`.

**The three eval runs are not included yet** — they require the tracer (root);
see below. Once `data/eval_run{1,2,3}.csv` exist, re-running
`python3 bench/eval_confusion.py` adds them and a pooled matrix automatically.

---

## Items 3, 5, 6 — scripts prepared, blocked on sudo

This agent session has **no passwordless sudo and no cached sudo timestamp**, so
it cannot run the eBPF tracer (root) or `apt-get install sysstat`. The following
are written, syntax-checked, and their non-root parts validated, ready to run
once sudo is available:

- **Item 3** — `bench/eval_runs.sh`: 3 runs, seeds 101/102/103, ~200 s each,
  tracer+traffic+all 9 attacks, into `data/eval_run{1,2,3}.csv` +
  `data/attack_log_run{1,2,3}.csv`. Hard-guarded to never write `data/eval.csv`
  or `data/attack_log.csv`; backs up and restores `data/pair_survey.json`;
  unpins the container on exit.
- **Item 5** — rerun `bash bench/run_all.sh demo 10 200000 baseline,in_kernel_unigram,in_kernel,naive_perevent`
  with `bash bench/pidstat_collector.sh` running in the background to capture
  steady-state collector CPU/RSS at 1 Hz (`pidstat -p <pid> 1`) per tracer into
  `bench/pidstat_steadystate.log`. Needs `sysstat` installed.
- **Item 6** — `bench/run_multi.sh` + `bench/bench_concurrent.py`: 3 nginx
  containers each traced by its own tracer, 50-concurrent-connection client,
  baseline vs traced. Creates/removes only `demo_m2`/`demo_m3` (never `demo`),
  uses the existing attachment check, restores `pair_survey.json`.
  Concurrent client validated against `demo` (no tracer): 50 conns, 462.8 rps,
  p50 56.7 ms, p99 714.9 ms, 0 errors over 6 s.


## 3. Three independent evaluation runs (item 3, RERUN with tracer)

`bash bench/eval_runs.sh demo` — three independent captures, each tracer +
nginx traffic (seed 101/102/103, 200 s) + all 9 attacks. `data/eval.csv` and
`data/attack_log.csv` left untouched; `data/pair_survey.json` restored; demo
left unpinned.

| Run | seed | windows | attacks | attack log |
|---|---|---|---|---|
| eval_run1 | 101 | 196 | 9 | data/attack_log_run1.csv |
| eval_run2 | 102 | 190 | 9 | data/attack_log_run2.csv |
| eval_run3 | 103 | 196 | 9 | data/attack_log_run3.csv |

Each attack log has the original 5 first, then the 4 new (cred_harvest,
html_drop, cpu_burn, port_scan). All CSVs are 77 columns.

---

## 4 (rerun). Confusion matrices across all 4 captures

`python3 bench/eval_confusion.py`. Threshold is the trained mean+3σ = 0.0182547
for every capture.

| Capture | windows | atk-win | Detector | TP | FP | TN | FN | Prec | Rec | F1 | FPR |
|---|---|---|---|---|---|---|---|---|---|---|---|
| eval.csv | 189 | 15 | Autoencoder | 10 | 0 | 174 | 5 | 1.000 | 0.667 | 0.800 | 0.000 |
| eval.csv | 189 | 15 | Security-rule | 10 | 0 | 174 | 5 | 1.000 | 0.667 | 0.800 | 0.000 |
| eval_run1 | 196 | 28 | Autoencoder | 26 | 80 | 88 | 2 | 0.245 | 0.929 | 0.388 | 0.476 |
| eval_run1 | 196 | 28 | Security-rule | 21 | 0 | 168 | 7 | 1.000 | 0.750 | 0.857 | 0.000 |
| eval_run2 | 190 | 32 | Autoencoder | 22 | 2 | 156 | 10 | 0.917 | 0.688 | 0.786 | 0.013 |
| eval_run2 | 190 | 32 | Security-rule | 21 | 0 | 158 | 11 | 1.000 | 0.656 | 0.793 | 0.000 |
| eval_run3 | 196 | 29 | Autoencoder | 27 | 73 | 94 | 2 | 0.270 | 0.931 | 0.419 | 0.437 |
| eval_run3 | 196 | 29 | Security-rule | 21 | 0 | 167 | 8 | 1.000 | 0.724 | 0.840 | 0.000 |
| **POOLED** | 771 | 104 | **Autoencoder** | 85 | 155 | 512 | 19 | **0.354** | **0.817** | **0.494** | **0.232** |
| **POOLED** | 771 | 104 | **Security-rule** | 73 | 0 | 667 | 31 | **1.000** | **0.702** | **0.825** | **0.000** |

**Per-attack detection: both detectors detect all 9 attacks in every run (9/9),
and all 5 in eval.csv — pooled 32/32 for each.** Autoencoder detection delays
ranged 0.04–1.39 s across the runs, the security-rule 0.26–1.39 s (the rule can
lag the AE by one window when the first overlapping window's anomaly is a volume
spike the AE catches before any security-family call lands).

### ⚠️ Finding: the autoencoder's FP=0 does NOT generalize beyond eval.csv

On the paper's `eval.csv`, the autoencoder has FP=0 / precision 1.000. On two of
the three fresh captures it false-positives on ~44–48% of **normal** windows
(run1 FPR 0.476, run3 0.437); run2 stayed at FPR 0.013. The security-family rule
holds **FP=0 on every capture**. Pooled, the rule beats the autoencoder on F1
(0.825 vs 0.494) and precision (1.000 vs 0.354); the autoencoder has higher
recall (0.817 vs 0.702) only because it over-fires.

This is not a pipeline bug — the same code reproduces `eval.csv` exactly
(FP=0). Diagnosis (normal windows only, vs threshold 0.0182547):

| Capture | normal-window median err | FP | FP windows' vocab-syscalls/win (median) | TN median |
|---|---|---|---|---|
| eval.csv | 0.00015 | 0 | — | 45 (all normal) |
| eval_run1 | 0.01252 | 80 | 234 | 24 |
| eval_run2 | 0.00030 | 2 | 2184 | 45 |
| eval_run3 | 0.01351 | 73 | 238 | 27 |

The false positives are **high-volume but legitimate** normal windows: run1/run3
simply ran busier (seeds 101/103 produced heavier `busy`/`burst` phases), the
whole capture's normal reconstruction error rose ~80×, and the fixed absolute
threshold does not adapt to traffic intensity. run2 happened to be as light as
the training/eval distribution and reproduced FP≈0; its only 2 FPs are extreme
bursts (median 2184 syscalls/window). This is the **same root cause** as the
documented "CPU pinning breaks the model" limitation: the model and its absolute
threshold are tied to the syscall-volume regime seen at training time.

Implication for the paper: the headline "FP 0 / precision 1.0" is specific to a
capture drawn from the training distribution and should be reported alongside
these three independent captures. A load-adaptive or rate-normalised threshold
is the obvious future work; the trivial security-family rule is the more robust
baseline here and strengthens the existing point that "the autoencoder does not
beat the baselines."


---

## 5 (rerun). Per-syscall microbenchmark — 4 conditions, 10 runs × 50,000 iters

`bash bench/run_item5.sh demo 10 50000` → `bench/results_item5.csv` (a fresh
file; `bench/results.csv`, the paper's session-B data, was not touched).

**Note on the data used.** The first launch's `exported=0` retry rule for
`naive_perevent` was wrong — the per-run tracer *was* attached (every naive run
is 395–586 µs/syscall), the retries only reflected that the tracer's `RESULT`
line was not being captured from its log. Per instruction, no reruns: the
summary below uses the existing rows, **taking the first 10 `naive_perevent`
rows as the 10 naive runs**, and ignores the (buggy) `valid` column. That column
also marked every `in_kernel*` row `valid=0` because the liveness check used
`kill -0` from the non-root harness against the root-owned tracer (EPERM), not
because the tracer was down.

Per-condition ns/syscall (10 runs each):

| Condition | mean | median | σ (pop.) | min | max | Δ mean vs base | × mean |
|---|---|---|---|---|---|---|---|
| baseline | 797.49 | 844.75 | 158.49 | 554.07 | 1017.18 | — | 1.00× |
| in_kernel_unigram | 796.79 | 828.13 | 131.64 | 485.21 | 928.73 | −0.70 ns | 1.00× |
| in_kernel (uni+bigram) | 1081.93 | 1116.32 | 233.31 | 609.96 | 1381.68 | +284.44 ns | 1.36× |
| naive_perevent | 463696.07 | 447626.08 | 56761.08 | 394570.82 | 585591.91 | +462898.58 ns | 581.44× |

Median-based overhead: unigram −16.61 ns (0.98×), in_kernel +271.57 ns (1.32×),
naive +446781.34 ns (529.89×).

**Reading these (50k-iteration runs are noisy).** At 50,000 iterations the
per-run spread is large (σ 132–233 ns on an ~800 ns baseline), so this session
does **not** cleanly resolve the small in-kernel costs: `in_kernel_unigram` comes
out statistically indistinguishable from baseline (−0.7 ns, inside the noise),
and `in_kernel` reads +284 ns / 1.36× — lower than the paper's 5M-iteration
session B (+356 ns / 1.70×) and within VM/sample variation. The paper's
microbenchmark figures should stay sourced from the 5M-iteration runs
(`bench/results.csv`); this 50k rerun corroborates only the **order** of the
effect. What it does resolve unambiguously is `naive_perevent`: **~581× mean
(530× median)** the baseline per-syscall cost, the same order as session A's
~896× and far outside any noise.

---

## 6. Overhead under multi-container and heavy load

`bash bench/run_item6.sh` (hard 30-min cap, no retry loops). Ran 04:19–04:32
(~12.5 min). Client: `bench/bench_concurrent.py` (closed-loop HTTP). **No failed
or skipped runs; all tracers attached.** Attachment checks: multi-container
demo/p17_nginx2/p17_nginx3 all OK (pids 34177/34210/34240), heavy-load demo OK
(pid 35166).

### Multi-container — 3 nginx containers, one tracer each (conc=1, 60 s × 3)

Tracers: `ebpf/tracer.py <c>` → `data/multi_<c>.csv`, all three attached at once.

| Container | untraced rps | traced rps | overhead |
|---|---|---|---|
| demo | 454.0 | 401.8 | −11.5% |
| p17_nginx2 | 413.8 | 420.0 | +1.5% |
| p17_nginx3 | 417.6 | 407.1 | −2.5% |
| **aggregate (n=9 each)** | **428.5** | **409.6** | **−4.4%** |

The per-container figures swing from −11.5% to +1.5% — the single-connection
closed-loop client is noisy on the 4-vCPU VM (consistent with the paper's
"below measurement resolution" nginx result). The aggregate −4.4% with all three
collectors running at once is within that run-to-run noise; running three
tracers simultaneously did not produce a throughput collapse.

### Heavy load — demo only, 50 concurrent connections (conc=50, 60 s × 3)

| Condition | runs (rps) | mean rps | overhead |
|---|---|---|---|
| untraced | 371.4, 364.5, 363.6 | 366.5 | — |
| traced | 363.5, 349.0, 372.1 | 361.5 | −1.4% |

Under 50-way concurrency the in-kernel tracer costs **−1.4%** throughput, again
within noise — the per-syscall cost (§5) stays negligible against nginx's
per-request network/disk work even at high concurrency.

### Collector CPU/RSS (`ps`, sampled every 5 s)

| Phase | tracer | %CPU median (min–max) | RSS median |
|---|---|---|---|
| multi_traced | demo | 1.9 (1.2–16.1) | 112.7 MB |
| multi_traced | p17_nginx2 | 2.7 (1.5–32.1) | 112.8 MB |
| multi_traced | p17_nginx3 | 1.6 (1.0–37.0) | 112.7 MB |
| heavy_traced | demo | 1.9 (1.1–49.6) | 112.7 MB |

As in `results.md §7`, `ps %cpu` is a lifetime average: it starts high (BCC
compile at attach, up to ~16–49%) and decays to a steady ~2–3% within the
60 s window. RSS is ~112–113 MB per tracer, essentially all BCC's embedded
LLVM (the maps are a few KB); three simultaneous tracers are three independent
BCC/Python processes, so RSS adds up linearly (~338 MB for three) — a
libbpf/CO-RE build would cut this to a few MB each.

**Failed runs: none.** Cleanup: p17_nginx2/p17_nginx3 removed, `bash kill.sh`
run, demo unpinned (cpuset 0-3), no tracer left running, `data/pair_survey.json`
restored (unchanged).
