# Project Status

**Last updated:** 17 October 2026 · **Next milestone:** Review 3 · **Paper due:** 31 Oct (ICCIDSDT-2027)

Syscall anomaly detection for Docker containers: an eBPF tracer counts a
container's syscalls inside the kernel, and an autoencoder trained on normal
traffic flags unusual windows. See [README.md](README.md) for the architecture.

---

## ⚠️ State change on 17 Oct: earlier results are superseded

The collection layer changed in two ways, both datasets were recaptured, and
the model has been retrained.

| Change | Before | After |
|---|---|---|
| Bigram features (`pair_01..50_count`) | all zero | **real**, in-kernel pair counts |
| Windowing | fixed 1 s, non-overlapping | **sliding: 2 s span, 1 s step** |
| Populated features | 21 of 74 | **71 of 74** (`stat_01`–`stat_03` still zero) |
| Training set | 628 windows | **585 windows** (`data/normal.csv`) |
| Evaluation set | 221 windows | **189 windows** (`data/eval.csv`) |
| Train / validation split | random | **by time** (overlapping rows never on both sides) |
| Threshold | 95th percentile | **mean + 3σ** of normal validation error |

**Superseded (do not quote):** TP 8 / FP 8 / TN 201 / FN 4, precision 0.500,
recall 0.667, F1 0.571, FPR 0.038, threshold 0.0015323, detection delays
0.57–1.04 s, training loss 0.000270 / validation 0.000323.

**Preserved for reproducibility:** `data/normal_unigram.csv`,
`data/eval_unigram.csv`, `data/attack_log_unigram.csv`, with the old model in
`person3_ml/models_unigram/` and its results in `person3_ml/results_unigram/`.

---

## Current results (retrained 17 Oct)

Model trained on 467 windows and validated on 117 (time-based split of
`data/normal.csv`; 1 window dropped for overlap). Evaluated on `data/eval.csv`:
189 windows, 15 attack, 174 normal.

| Detector | Threshold | TP | FP | TN | FN | Precision | Recall | F1 | FPR | Attacks |
|---|---|---|---|---|---|---|---|---|---|---|
| **Autoencoder** | **mean + 3σ = 0.0138062** | **10** | **1** | **173** | **5** | **0.9091** | **0.6667** | **0.7692** | **0.0057** | **5/5** |
| Autoencoder | p95 = 0.0032245 | 10 | 11 | 163 | 5 | 0.4762 | 0.6667 | 0.5556 | 0.0632 | 5/5 |
| Autoencoder | p99 = 0.0258890 | 10 | 0 | 174 | 5 | 1.0000 | 0.6667 | 0.8000 | 0.0000 | 5/5 |
| One-Class SVM | mean + 3σ | 10 | 0 | 174 | 5 | 1.0000 | 0.6667 | 0.8000 | 0.0000 | 5/5 |
| Isolation Forest | mean + 3σ | 0 | 0 | 174 | 15 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0/5 |

- **Curves (autoencoder):** average precision 0.7078, ROC AUC 0.7973
  (`person3_ml/results/pr_roc_curves.png`).
- **Windows flagged per attack:** recon 2/2, drop_exec 2/2, outbound_conn 2/7,
  ns_escape 2/2, spawn_storm 2/2. Most outbound_conn windows are a hung
  connection that looks idle.
- **Reconstruction error:** attack median 16.84 (max 3396.07); normal median
  0.000215 (max 0.0138).
- **Detection delay:** recon 0.76 s, drop_exec 1.01 s, outbound_conn 0.53 s,
  ns_escape 0.97 s, spawn_storm 0.66 s. Mean about 0.79 s, max 1.01 s.
- **Training:** 100 epochs; final training loss 0.00150763, validation loss
  0.00125739.
- **Scoring time:** median 0.144 ms per window (Apple Silicon laptop).
- **One-Class SVM matches the autoencoder** on this data, so the paper should
  not claim the autoencoder beats the baselines.
- **Pair-selection check:** the pair columns chosen with help from attack data
  (see Team decisions) were zeroed and the eval re-scored. Result: still 5/5
  attacks, TP 10, FP 0. Detection does not depend on them.

Reproduce with `python3 -m person3_ml.evaluate data/eval.csv data/attack_log.csv`
and `python3 -m person3_ml.baselines data/normal.csv data/eval.csv data/attack_log.csv`.

---

## At a glance

| Area | Owner | Status |
|---|---|---|
| eBPF collection, workloads, datasets, benchmark | Naman | ✅ Bigrams, sliding windows, microbenchmark done · demo rehearsal and 2 reruns pending |
| Data pipeline, retraining, evaluation, baselines | Krishita | ✅ Retrained and evaluated on the new data |
| Original autoencoder model | Abhiram | ✅ Done (retraining handed over to Krishita) |
| Paper | Team | 🟠 Update evaluation section with the current results |

---

## Naman: collection layer (Member 1)

**Owns:** `ebpf/`, `workload/`, `demo/`, `bench.py`, `analyze.py`, datasets in `data/`

### Done

| Work | Where |
|---|---|
| eBPF syscall counter on `raw_syscalls:sys_enter`, filtered by container cgroup | `ebpf/tracer.py` |
| Lossless delta counting: counters never cleared, each window is a difference | `ebpf/tracer.py` |
| **In-kernel bigram counting**: consecutive syscall pairs, keyed per thread | `ebpf/tracer.py` |
| **Sliding windows**: 2 s span emitted every 1 s, so an attack crossing a boundary lands whole in at least one window | `ebpf/tracer.py` |
| 20-syscall vocabulary with family grouping (`open`+`openat`, `clone`+`clone3`+`fork`+`vfork`, …) | `ebpf/vocab.py`, `docs/VOCAB.md` |
| **Pair selection**: all 400 vocab transitions counted in-kernel, 50 emitted as columns | `ebpf/pick_pairs.py`, `ebpf/pairs.json` |
| Normal traffic generator (4 load phases) and 5 simulated attacks with per-attack timeout | `workload/` |
| Training capture: **585 windows**, 10 min nginx traffic, no attacks | `data/normal.csv` |
| Evaluation capture: **189 windows**, traffic (seed 99) + 5 attacks | `data/eval.csv`, `data/attack_log.csv` |
| Overhead benchmark harness + naive per-event tracer as the comparison baseline | `bench.py`, `ebpf/naive_tracer.py`, `data/bench.jsonl` |
| Per-syscall cost microbenchmark (`getpid` loop in the container), 3 conditions in one session, attachment checked | `bench/`, `results.md` |
| Per-attack detection delay and `unshare` analysis | `analyze.py` |
| Live demo watcher: prints NORMAL / ALERT per window with triggering syscalls | `demo/watch.py` |
| `unshare` check run: "Operation not permitted", so seccomp is confirmed | — |
| Retrain handoff | `handoff_krishita_retrain.md` |

### Findings

- **The in-kernel tracer adds 405 ns per syscall** (median 1,037.73 vs 632.59 ns
  on a `getpid` loop, 1.64×). Per-event export adds 566,136 ns (896×). Measured
  on the bigram tracer; see [results.md](results.md).
- **Per-event export costs 72.8% of nginx throughput** (472.0 → 128.3 rps over
  10-run sets, 3.7× slowdown, 3.9× p50 latency). Measured on the unigram tracer;
  needs a rerun on the bigram tracer.
- **The in-kernel tracer's overhead is below measurement resolution on this VM.**
  Across 3- and 10-run sets the traced/untraced difference fell inside run-to-run
  variance (σ ≈ 50–68 rps on a ~470 rps mean, ±14%), and in one set traced measured
  *faster*. Reported as "below resolution" rather than as a precise figure.
- **One 10-run naive set (1022 rps) is excluded.** It is faster than no tracing,
  so the tracer was most likely not attached. It stays in `bench.jsonl`, and the
  paper explains the exclusion.
- **`unshare` is invisible to `sys_enter`.** It never appears in any capture. The
  confirming check returned "Operation not permitted": Docker's default seccomp
  profile rejects the call before the tracepoint fires. `ns_escape` is still
  detected, via `execve`/`clone` from the `docker exec` wrapper.
- **Pair counts separate attack from normal**: normal nginx traffic shows about
  7 distinct active pairs per window; attack windows showed 19–27.
- **nginx's request loop is recoverable from the bigrams**:
  `epoll_wait → recvfrom → openat → sendfile → write → close`.
- **`clone → execve` is not observable**: bigrams are keyed per thread, and the
  two calls happen in different processes.

### Pending

| Item | Why it matters | Priority |
|---|---|---|
| Pull `main` on the VM and rehearse the live demo with the retrained model | Nobody has run it end to end since the retrain. The VM has scikit-learn 1.7.2; the model was saved with 1.6.1 | 🔴 Before Review 3 |
| Fix `collector_stats` in `bench/run_all.sh` and rerun | It measures the `sudo` helper process, not the tracer (0.0% CPU, ~2.4 MB for both tracers). Don't cite those columns until fixed | 🟠 Before Review 3 |
| Re-run nginx throughput on the bigram tracer, confirming attachment, and append to `bench.jsonl` | Current throughput figures are from the unigram tracer | 🟠 Before Review 3 |
| Unigram-only microbenchmark (tracer from commit `879595a`) | Shows how much of the 405 ns the bigrams cost. About 3 minutes | 🟡 Strong for the paper |
| Event loss under a faster consumer and workload | The measured 0% loss doesn't show per-event export is lossless: the slow consumer throttled the workload | 🟡 Strong for the paper |
| Distinct and total syscalls per window | Requested for the paper | 🟡 Planned |
| Update the kernel version in the paper draft (6.8.0-138, not 134) | The VM updated | 🟡 For the paper |
| `stat_01`–`stat_03` (inter-arrival mean/std, error count) | Still zero. Needs a `sys_exit` hook and timestamp tracking | ⚪ Future work |
| Overhead on bare metal | The VM varies by about ±14% between runs | ⚪ Future work |

---

## Krishita: data pipeline, retraining and evaluation (Member 2)

**Owns:** `member2/`, `tests/`, retraining and evaluation in `person3_ml/`, the CSV contract, README and docs, the repository

### Done

| Work | Where |
|---|---|
| CSV contract: 77 columns, row rules, metadata types; now allows overlapping sliding windows | `docs/naman_krishita_csv_contract.md` |
| Feature schema: one column list shared by the tracer, validator and model | `member2/schema.py` |
| 6-stage pipeline: load → validate → map columns → separate metadata → build `X` | `member2/` |
| Mock data generator for development before real data existed | `member2/mock_aggregated_csv.py` |
| Real-data integration, including the new bigram + sliding-window captures (585×74, 189×74) unchanged | `member2/pipeline.py` |
| Stricter validation for the resolved rules (`cgroup_id` type, statistic ranges) | `member2/validation.py` |
| Evaluation labelling from the attack log, including overlapping windows | `member2/evaluation_labels.py` |
| Single-window preparation for the live demo (`prepare_window`) | `member2/pipeline.py` |
| Live scoring functions: `score_window`, `anomaly_threshold` (signatures unchanged) | `person3_ml/detect.py` |
| **Retraining**: time-based split, mean + 3σ threshold, p95/p99 saved for comparison | `person3_ml/train.py`, `person3_ml/models/` |
| **Evaluation**: every paper number in one run, plus PR and ROC curves | `person3_ml/evaluate.py`, `person3_ml/results/` |
| **Baselines** on identical features: Isolation Forest, One-Class SVM | `person3_ml/baselines.py` |
| Pair-selection check: results unchanged with the attack-informed pair columns zeroed | See Current results |
| Unigram model, results and attack log preserved | `person3_ml/*_unigram/`, `data/attack_log_unigram.csv` |
| Error-over-time plot for the evaluation capture | `person3_ml/plot_timeline.py`, `person3_ml/results/eval_error_timeline.png` |
| Library versions pinned to the ones the model was trained with | `requirements-ml.txt` |
| 22 automated tests (22/22 pass), including real unigram and sliding-window samples | `tests/` |
| README updated for bigrams, sliding windows and current results | `README.md` |
| Independent verification of evaluation and benchmark numbers | Caught the 1022 rps run, the delay wording, and the pair-selection issue |

### Pending

| Item | Priority |
|---|---|
| Retrain and re-evaluate if the team re-picks the pairs from normal-only traffic | 🟠 Only if decided |
| Rename placeholder columns (`pair_37_count` → readable) | ⚪ Future work |

---

## Abhiram: anomaly model (Member 3)

**Owns:** the autoencoder design in `person3_ml/`

### Done

| Work | Where |
|---|---|
| Autoencoder: 74 → 64 → 32 → 8 → 32 → 64 → 74 | `person3_ml/autoencoder.py` |
| Scaler that handles constant-zero columns | `person3_ml/preprocessing.py` |
| Original training pipeline and unigram model (100 epochs, seed 42) | `person3_ml/train.py`, `person3_ml/models_unigram/` |
| Batch detection script | `person3_ml/detect.py` |
| Training-loss and reconstruction-error plots | `person3_ml/plot_results.py` |

### Pending

Retraining was handed over to Krishita and is done. Open item:

| Item | Why it matters | Priority |
|---|---|---|
| Note library versions | Old scaler saved with scikit-learn 1.9.1; reproduces with 1.6.1; VM has 1.7.2 and warns. The retrained model was trained with scikit-learn 1.6.1 and torch 2.8.0 | 🟡 For the paper |

---

## Team decisions

| Decision | Outcome |
|---|---|
| Bigrams before Review 3? | **Yes, reversed 17 Oct.** Implemented with sliding windows; both datasets recaptured. The paper describes 74 features with 71 populated. |
| Sliding windows? | **Yes.** An attack crossing a window boundary lands whole in at least one window. Costs row independence, which the paper must acknowledge. |
| How the 50 pairs were chosen | **33 transitions observed in a survey capture of nginx traffic plus the 5 simulated attacks, plus 17 hand-picked post-exploitation transitions.** The survey included attack traffic, so the paper must say so. Normal traffic alone shows only 7 transitions. Zeroing the attack-informed columns leaves detection unchanged (5/5, FP 0). **Open:** keep and disclose, or re-pick from normal-only traffic (needs both captures redone and a retrain). |
| Headline threshold | **mean + 3σ** of normal validation error, with the PR curve and the p95/p99 points for comparison. |
| Train / validation split | **By time.** Sliding windows overlap, so a random split would put near-duplicate rows on both sides. |
| Retraining owner | **Krishita**, taking over from Abhiram. |
| Demo false alerts | **Explain upfront** if one appears. At mean + 3σ, 1 of 174 normal eval windows was flagged. |

---

## Environment

- Ubuntu 22.04 on VirtualBox, **kernel 6.8.0-138-generic** (updated from 6.8.0-134;
  the paper draft still says 134)
- **4 vCPU, ~6 GB RAM**
- Docker, cgroup v2, BCC (`python3-bpfcc`), x86_64 only (syscall numbers are
  architecture-specific)
- Demo container: `docker run -d --name demo nginx`
- Model training: Python 3.9, torch 2.8.0, scikit-learn 1.6.1

## Demo checklist

1. `docker start demo` (or `docker run -d --name demo nginx` the first time)
2. Terminal 1: `python3 demo/watch.py data/live.csv`. **Start this first**: it waits
   for the file, so it doesn't replay old rows all at once.
3. Terminal 2: `sudo python3 ebpf/tracer.py demo data/live.csv`. Wait for the
   watcher to print the threshold.
4. Terminal 3: `python3 workload/normal_traffic.py demo 600`
5. Trigger an attack: `bash workload/attack.sh demo`. Expect an ALERT within
   about 1 s.

The demo uses the retrained model in `person3_ml/models/`. Pull `main` on the
VM before the demo.
