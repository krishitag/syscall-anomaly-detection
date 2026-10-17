# Project Status

**Last updated:** 17 October 2026 · **Next milestones:** Review 3 (paper + live demo), conference deadline 31 October

Syscall anomaly detection for Docker containers: an eBPF tracer counts a
container's syscalls inside the kernel, and an autoencoder trained on normal
traffic flags unusual windows. See [README.md](README.md) for the
architecture.

## Current plan: bigrams and sliding windows

The team is adding syscall-pair (bigram) counts and switching to sliding
windows before Review 3. See [handoff_krishita_retrain.md](handoff_krishita_retrain.md).

| | Before (unigram results) | After (in progress) |
|---|---|---|
| Populated features | 21 of 74 | 71 of 74 |
| Window | 1 s, no overlap | 2 s span, one row every 1 s |
| Train / validation split | Random | By time (no overlap between the two) |
| Threshold | 95th percentile | mean + 3σ, plus a precision-recall curve |

This means the model, scaler, threshold and every paper number change. The
current results are kept as the unigram baseline (`data/*_unigram.csv`).

## At a glance

| Area | Owner | Status |
|---|---|---|
| eBPF collection, bigrams, sliding windows, new captures | Naman | 🟠 In progress |
| Data pipeline, retraining, evaluation, baselines | Krishita | ✅ Code ready · waiting for new data |
| Original autoencoder model | Abhiram | ✅ Done (retraining handed over to Krishita) |
| Paper | Team | 🟠 Evaluation section waits on the retrain |

**Unigram baseline result** (to be replaced): on the old `eval.csv` (221
windows, 12 attack windows), TP 8, FP 8, TN 201, FN 4. That is precision
0.500, recall 0.667, F1 0.571 and FPR 0.038, with 5 of 5 attacks detected.
Mean detection delay is 0.76 s and the maximum is 1.04 s.

---

## Naman: collection layer (Member 1)

**Owns:** `ebpf/`, `workload/`, `demo/`, `bench.py`, `analyze.py`, datasets in `data/`

### Done

| Work | Where |
|---|---|
| eBPF syscall counter on `raw_syscalls:sys_enter`, filtered by container cgroup | `ebpf/tracer.py` |
| 1-second windowed tracer, writing the agreed 77-column CSV | `ebpf/tracer.py` |
| 20-syscall vocabulary, revised after the first real capture | `ebpf/vocab.py`, `docs/VOCAB.md` |
| Normal traffic generator and 5 simulated attacks (with a 5 s timeout per attack) | `workload/` |
| Unigram captures: training (628 windows) and evaluation (221 windows + attack log) | `data/` |
| Overhead benchmark: naive per-event tracer vs. in-kernel tracer | `bench.py`, `ebpf/naive_tracer.py`, `data/bench.jsonl` |
| Per-attack detection delay and unshare analysis | `analyze.py` |
| Live demo watcher: prints NORMAL / ALERT for each window | `demo/watch.py` |
| Retraining handoff | `handoff_krishita_retrain.md` |

**Key findings:**
- Per-event export costs 72.8% of nginx throughput (3.7× slowdown, 3.9× p50 latency).
- The in-kernel tracer's overhead is below the measurement noise on the VM.

### Pending

| Item | Why it matters | Priority |
|---|---|---|
| Bigram counting and sliding windows in the tracer | Needed for the 71-feature model | 🔴 Blocks retraining |
| New `normal.csv` (at least 10 min), `eval.csv` and `attack_log.csv`; keep old ones as `*_unigram.csv` | Retraining and every paper number depend on them | 🔴 Blocks retraining |
| Pair mapping for the 50 pair columns | Needed to interpret bigram features | 🔴 With the new captures |
| Run the `unshare` check in the demo container | "Operation not permitted" confirms seccomp. "Command not found" means ns_escape never ran | 🔴 Before submission |
| Rerun all 3 benchmark conditions in one session, confirming the naive tracer is attached, and append to `bench.jsonl` | One naive run (1022 rps) was faster than no tracing. It stays in the raw data, and the paper explains why it was excluded | 🟠 Before Review 3 |
| Measure distinct and total syscalls per window | Requested for the paper | 🟡 Planned |
| `stat_01`–`stat_03` (timing and error statistics) | Still not implemented | ⚪ Future work |
| Overhead on bare metal | The VM varies by about ±14% between runs | ⚪ Future work |

---

## Krishita: data pipeline, retraining and evaluation (Member 2)

**Owns:** `member2/`, `tests/`, retraining and evaluation in `person3_ml/`, the CSV contract, README and docs, the repository

### Done

| Work | Where |
|---|---|
| CSV contract agreed with Naman (now allows overlapping sliding windows) | `docs/naman_krishita_csv_contract.md` |
| Feature schema: one column list shared by the tracer, validator and model | `member2/schema.py` |
| 6-stage pipeline: load → validate → map columns → separate metadata → build `X` | `member2/` |
| Mock data generator for development before real data existed | `member2/mock_aggregated_csv.py` |
| Real-data integration: Naman's CSV passes with no code changes | `member2/pipeline.py` |
| Stricter validation for the resolved rules (`cgroup_id` type, statistic ranges) | `member2/validation.py` |
| Evaluation labelling from the attack log, including overlapping windows | `member2/evaluation_labels.py` |
| Single-window preparation for the live demo (`prepare_window`) | `member2/pipeline.py` |
| Live scoring functions: `score_window`, `anomaly_threshold` | `person3_ml/detect.py` |
| Retraining code: time-based split, mean + 3σ threshold (p95/p99 saved for comparison) | `person3_ml/train.py` |
| Evaluation of every paper number in one run, plus PR and ROC curves | `person3_ml/evaluate.py` |
| Baselines on identical features: Isolation Forest, One-Class SVM | `person3_ml/baselines.py` |
| Dry run of retrain → evaluate → baselines on the unigram data | Works end to end |
| 18 automated tests (18/18 pass), including a sample of real data | `tests/` |
| README with architecture, contract, schema and handoff docs | `README.md`, `docs/` |
| Independent check of all unigram evaluation and benchmark numbers | All paper values match |
| Repository maintenance and merging both integration PRs | PR #1, PR #2 |

### Pending

| Item | Priority |
|---|---|
| Retrain on the new `normal.csv` (`python3 -m person3_ml.train data/normal.csv`) | 🔴 When Naman's data lands |
| Evaluate and run baselines on the new `eval.csv`; send all numbers for the paper | 🔴 After retraining |
| Check the new captures pass validation and the attack windows are labelled correctly | 🔴 When Naman's data lands |
| Update README results and the test fixture for the new data | 🟠 After retraining |
| Rename placeholder columns (`pair_37_count`, etc.) to readable names (team decision) | ⚪ Future work |

---

## Abhiram: anomaly model (Member 3)

**Owns:** the autoencoder design in `person3_ml/`

### Done

| Work | Where |
|---|---|
| Autoencoder: 74 → 64 → 32 → 8 → 32 → 64 → 74 | `person3_ml/autoencoder.py` |
| Scaler that handles constant-zero columns | `person3_ml/preprocessing.py` |
| Original training pipeline and unigram model (100 epochs, 95th-percentile threshold) | `person3_ml/train.py`, `person3_ml/models/` |
| Batch detection script | `person3_ml/detect.py` |
| Training-loss and reconstruction-error plots | `person3_ml/plot_results.py`, `person3_ml/results/` |

**Unigram model numbers:** final training loss 0.000270, validation loss
0.000323; scoring takes about 0.14 ms per window.

### Pending

Retraining has been handed over to Krishita. No open items.

---

## Team decisions

| Decision | Outcome |
|---|---|
| Bigrams before Review 3? | **Yes.** Bigram counts and sliding windows are being added. The unigram results stay as a baseline. |
| Threshold | **mean + 3σ** of normal validation error, reported with a precision-recall curve. The 95th and 99th percentiles are shown for comparison. |
| Train / validation split | **By time.** Sliding windows overlap, so a random split would put near-duplicate rows on both sides. |
| Retraining owner | **Krishita**, taking over from Abhiram. |

## Demo checklist

1. `docker run -d --name demo nginx`
2. Terminal 1: `python3 demo/watch.py data/live.csv`. It waits for the file;
   start it first so it doesn't replay old rows all at once.
3. Terminal 2: `sudo python3 ebpf/tracer.py demo data/live.csv`. Wait for the
   watcher to print the threshold.
4. Terminal 3: `python3 workload/normal_traffic.py demo 600`
5. Trigger an attack, e.g. `bash workload/attack.sh demo`. Expect an ALERT
   within about 1 s.

The demo needs the retrained model. The current model does not fit
sliding-window data.
