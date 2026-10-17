# Project Status

**Last updated:** 17 October 2026 · **Next milestone:** Review 3 · **Paper due:** 31 Oct (ICCIDSDT-2027)

Syscall anomaly detection for Docker containers: an eBPF tracer counts a
container's syscalls inside the kernel, and an autoencoder trained on normal
traffic flags unusual windows. See [README.md](README.md) for the architecture.

---

## ⚠️ State change on 17 Oct — all previous results are superseded

The collection layer changed in two ways today. **Every evaluation number
produced before 17 Oct describes data that no longer exists**, and the
committed model cannot score the new captures.

| Change | Before | After |
|---|---|---|
| Bigram features (`pair_01..50_count`) | all zero | **real**, in-kernel pair counts |
| Windowing | fixed 1 s, non-overlapping | **sliding: 2 s span, 1 s step** |
| Populated features | 21 of 74 | **71 of 74** (`stat_01`–`stat_03` still zero) |
| Training set | 628 windows | **585 windows** (`data/normal.csv`, recaptured) |
| Evaluation set | 221 windows | **189 windows** (`data/eval.csv`, recaptured) |

This reverses the earlier "no bigrams before Review 3" decision. The paper can
now describe a 74-feature vector with 71 populated, rather than 21.

**Superseded (do not quote):** TP 8 / FP 8 / TN 201 / FN 4, precision 0.500,
recall 0.667, F1 0.571, FPR 0.038, threshold 0.0015323, detection delays
0.57–1.04 s, training loss 0.000270 / validation 0.000323. All of these were
computed on the 21-feature, non-overlapping data.

**Preserved for reproducibility:** `data/normal_unigram.csv`,
`data/eval_unigram.csv` hold the pre-17-Oct captures.

**Still valid:** the overhead benchmark comparison (per-event export vs
in-kernel aggregation) is a property of the collection layer, not the model —
but it should be re-run now that bigrams add work per event.

---

## At a glance

| Area | Owner | Status |
|---|---|---|
| eBPF collection, workloads, datasets, benchmark | Naman | ✅ Bigrams + sliding windows done · benchmarks need re-running |
| Data contract, pipeline, labels, integration, docs | Krishita | ✅ Done · accepts new captures unchanged |
| Autoencoder model, training, detection | Abhiram | 🔴 **Retrain required** |
| Paper | Team | 🟠 Drafted · all evaluation numbers pending retrain |

---

## Naman: collection layer (Member 1)

**Owns:** `ebpf/`, `workload/`, `demo/`, `bench.py`, `analyze.py`, datasets in `data/`

### Done

| Work | Where |
|---|---|
| eBPF syscall counter on `raw_syscalls:sys_enter`, filtered by container cgroup | `ebpf/tracer.py` |
| Lossless delta counting — counters never cleared, each window is a difference | `ebpf/tracer.py` |
| **In-kernel bigram counting** — consecutive syscall pairs, keyed per thread | `ebpf/tracer.py` |
| **Sliding windows** — 2 s span emitted every 1 s, so boundary-straddling attacks land whole in at least one window | `ebpf/tracer.py` |
| 20-syscall vocabulary with family grouping (`open`+`openat`, `clone`+`clone3`+`fork`+`vfork`, …) | `ebpf/vocab.py`, `docs/VOCAB.md` |
| **Pair selection**: all 400 vocab transitions counted in-kernel, 50 emitted as columns | `ebpf/pick_pairs.py`, `ebpf/pairs.json` |
| Normal traffic generator (4 load phases) and 5 simulated attacks with per-attack timeout | `workload/` |
| Training capture: **585 windows**, 10 min nginx traffic, no attacks | `data/normal.csv` |
| Evaluation capture: **189 windows**, traffic (seed 99) + 5 attacks | `data/eval.csv`, `data/attack_log.csv` |
| Overhead benchmark harness + naive per-event tracer as the comparison baseline | `bench.py`, `ebpf/naive_tracer.py`, `data/bench.jsonl` |
| Per-attack detection delay and `unshare` analysis | `analyze.py` |
| Live demo watcher: prints NORMAL / ALERT per window with triggering syscalls | `demo/watch.py` |
| Retrain handoff for Abhiram | `docs/handoff_abhiram_retrain.md` |

### Findings

- **Per-event export costs 72.8% of nginx throughput** (517.8 → 128.3 rps, 3.7× slowdown,
  3.9× p50 latency). Measured against the in-kernel design on identical attach points.
- **The in-kernel tracer's overhead is below measurement resolution on this VM.** Across 3-
  and 10-run sets the traced/untraced difference fell inside run-to-run variance
  (σ ≈ 50–68 rps on a ~470 rps mean, ±14%), and in one set traced measured *faster*. Reported
  as "below resolution" rather than as a precise figure the data cannot support.
- **`unshare` is invisible to `sys_enter`**: 0 occurrences across all 221 windows of the old
  eval capture. Docker's default seccomp profile rejects the call before the tracepoint fires.
  `ns_escape` was still flagged, but via `execve`/`clone` from the `docker exec` wrapper, not
  its signature syscall. **Needs the confirming command below.**
- **Pair counts alone separate attack from normal**: normal nginx traffic shows ~7 distinct
  active pairs per window; attack windows showed 19–27.
- **nginx's request loop is recoverable from the bigrams**:
  `epoll_wait → recvfrom → openat → sendfile → write → close`, the six highest-frequency
  transitions observed.
- Only **33 distinct vocab transitions** occur in baseline traffic, so 17 of the 50 pair
  columns are hand-picked plausible post-exploitation transitions that were unobserved at
  selection time. The paper must state how the 50 were chosen.

### Pending

| Item | Why it matters | Priority |
|---|---|---|
| Run `docker exec demo unshare --user --map-root-user true; echo $?` | "Operation not permitted" confirms seccomp. "Command not found" means `ns_escape` never ran and results must be redone without it | 🔴 Before submission |
| Re-run all 3 benchmark conditions in one session on the bigram tracer, confirming the naive tracer is attached each time | Bigrams add ~2 map operations per event, so the current overhead figures understate the shipped system | 🔴 Before Review 3 |
| ns/syscall microbenchmark (tight `getpid` loop, in-container) | Throughput on nginx is variance-limited; a syscall-only microbenchmark resolves the per-event tax directly | 🟠 Before Review 3 |
| Event-loss measurement on the naive tracer under load | Per-event export drops events under load; in-kernel aggregation cannot by construction. A correctness argument, not just a speed one | 🟠 Strong for the paper |
| Collector CPU% and RSS during a run | Requested for the paper | 🟡 Planned |
| Distinct and total syscalls per window | Requested for the paper; quantifies how small each map read is | 🟡 Planned |
| `stat_01`–`stat_03` (inter-arrival mean/std, error count) | Still zero. Needs `sys_exit` hook and timestamp tracking | ⚪ Future work |
| Overhead on bare metal | The VM varies by about ±14% between runs | ⚪ Future work |

---

## Krishita: data pipeline and integration (Member 2)

**Owns:** `member2/`, `tests/`, the CSV contract, README and docs, the repository

### Done

| Work | Where |
|---|---|
| CSV contract: 77 columns, row rules, metadata types | `docs/naman_krishita_csv_contract.md` |
| Feature schema: one column list shared by the tracer, validator and model | `member2/schema.py` |
| 6-stage pipeline: load → validate → map columns → separate metadata → build `X` | `member2/` |
| Mock data generator for development before real data existed | `member2/mock_aggregated_csv.py` |
| Real-data integration: Naman's CSV passes with no code changes | `member2/pipeline.py` |
| **Accepts the new bigram + sliding-window captures unchanged** (585×74, 189×74 verified) | `member2/pipeline.py` |
| Stricter validation for the resolved rules (`cgroup_id` type, statistic ranges) | `member2/validation.py` |
| Evaluation labelling from the attack log, including boundary-crossing attacks | `member2/evaluation_labels.py` |
| Single-window preparation for the live demo (`prepare_window`) | `member2/pipeline.py` |
| Model integration: `score_window`, `anomaly_threshold`, evaluation script | `person3_ml/detect.py`, `person3_ml/evaluate.py` |
| 18 automated tests (18/18 pass), including a real-data sample | `tests/` |
| README with architecture, contract, schema and handoff docs | `README.md`, `docs/` |
| Independent verification of every evaluation and benchmark number against the data | Caught the invalid 1022 rps benchmark run and the delay-wording error |
| Threshold sensitivity analysis and baselines (Isolation Forest, One-Class SVM) | Shared with the team, not yet committed |

### Pending

| Item | Why it matters | Priority |
|---|---|---|
| Re-verify all numbers once Abhiram retrains | Every evaluation figure changes | 🔴 After retrain |
| Commit the Isolation Forest / One-Class SVM baselines | A non-deep baseline on identical features strengthens the evaluation section | 🟠 For the paper |
| Note that overlapping rows are not independent samples | Worth one sentence in the paper's methodology | 🟡 For the paper |
| Rename placeholder columns (`pair_37_count` → readable) | Needed for the report, where `pair_37` is not a usable label | ⚪ Future work |

---

## Abhiram: anomaly model (Member 3)

**Owns:** `person3_ml/` (model, training, detection, plots)

### Done

| Work | Where |
|---|---|
| Autoencoder: 74 → 64 → 32 → 8 → 32 → 64 → 74 | `person3_ml/autoencoder.py` |
| Scaler fitted on normal training data only | `person3_ml/preprocessing.py` |
| Training pipeline, 100 epochs, seed 42 | `person3_ml/train.py` |
| Batch detection and per-window scoring | `person3_ml/detect.py` |
| Training-loss and reconstruction-error plots | `person3_ml/plot_results.py`, `person3_ml/results/` |
| Scoring latency: ~0.14 ms per window | measured pre-17-Oct, likely still representative |

### Pending — blocking everything downstream

| Item | Why it matters | Priority |
|---|---|---|
| **Retrain on the new 585-window `data/normal.csv`** | The committed scaler was fitted where 50 columns were constant zero; those columns now carry real counts. Scoring new data with it produces numbers, and they are garbage | 🔴 Blocking |
| **Split by time, not randomly** | Sliding windows overlap by 1 s, so a random train/validation split leaks near-identical rows across both sides and validation loss comes out artificially low | 🔴 Blocking |
| Recompute the threshold on new normal data only | `0.0015323` is meaningless against the new error distribution | 🔴 Blocking |
| **Change the threshold rule, and report a PR curve** | The 95th percentile flags ~5% of normal windows *by construction* — that is where precision 0.500 came from. It is an artifact of the rule, not a property of the model | 🟠 Before demo |
| Re-run evaluation and report TP/FP/TN/FN, precision, recall, F1, FPR, per-attack flagged windows | Paper's entire results section | 🔴 Blocking |
| Mean and max reconstruction error, attack vs normal windows, and the ratio | "Attack windows scored N× higher" is a strong line for the paper | 🟠 For the paper |
| Final training and validation loss on the new data | Paper | 🟠 For the paper |
| Keep `score_window(x)` and `anomaly_threshold()` signatures | `demo/watch.py` depends on both | 🔴 Do not break |
| Note library versions | Scaler saved with scikit-learn 1.9.1; reproduces with 1.6.1; VM has 1.7.2 and warns | 🟡 For the paper |

---

## Team decisions

| Decision | Outcome |
|---|---|
| Bigrams before Review 3? | **Yes — reversed 17 Oct.** Implemented with sliding windows; both datasets recaptured. The paper now describes 74 features with 71 populated. |
| Sliding windows? | **Yes.** Fixes the boundary-straddling tail windows that caused the 4 false negatives. Costs row independence, which the paper must acknowledge. |
| How the 50 pairs were chosen | **33 highest-frequency transitions observed in baseline traffic + 17 hand-picked plausible post-exploitation transitions.** Stated as method in the paper. |
| Headline threshold | **Open.** 95th percentile produced precision 0.500 on the old data. Decide on the new data from a PR curve rather than one operating point. |
| Demo false alerts | **Explain upfront** if one appears, and state the operating point. |

---

## Environment

- Ubuntu 22.04 on VirtualBox, **kernel 6.8.0-138-generic** (updated from 6.8.0-134; the
  paper draft still says 134)
- **4 vCPU, ~6 GB RAM**
- Docker, cgroup v2, BCC (`python3-bpfcc`), x86_64 only (syscall numbers are
  architecture-specific)
- Demo container: `docker run -d --name demo nginx`

## Demo checklist

1. `docker start demo` (or `docker run -d --name demo nginx` the first time)
2. Terminal 1: `python3 demo/watch.py data/live.csv` — **start this first**, it waits for the
   file, so it doesn't replay old rows all at once
3. Terminal 2: `sudo python3 ebpf/tracer.py demo data/live.csv` — wait for the watcher to
   print the threshold
4. Terminal 3: `python3 workload/normal_traffic.py demo 600`
5. Trigger an attack: `bash workload/attack.sh demo`. Expect an ALERT within about 1 s.

**The demo will not work correctly until Abhiram retrains** — `watch.py` scores the new
74-feature rows with a model fitted on the old 21-feature data.
