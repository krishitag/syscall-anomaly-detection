# Project Status

**Last updated:** 16 October 2026 · **Next milestone:** Review 3

Syscall anomaly detection for Docker containers: an eBPF tracer counts a
container's syscalls inside the kernel, and an autoencoder trained on normal
traffic flags unusual one-second windows. See [README.md](README.md) for the
architecture.

## At a glance

| Area | Owner | Status |
|---|---|---|
| eBPF collection, workloads, datasets, benchmark | Naman | ✅ Done for Review 3 · 2 checks pending |
| Data contract, pipeline, labels, integration, docs | Krishita | ✅ Done for Review 3 |
| Autoencoder model, training, detection | Abhiram | ✅ Done for Review 3 · threshold choice open |
| Paper | Team | ✅ Drafted · depends on the unshare check |

**Headline result:** on `data/eval.csv` (221 windows, 12 attack windows), the
committed model scores TP 8, FP 8, TN 201, FN 4. That is precision 0.500,
recall 0.667, F1 0.571 and FPR 0.038, with 5 of 5 attacks detected. Mean
detection delay is 0.76 s and the maximum is 1.04 s.

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
| Training capture: 628 windows of nginx traffic | `data/normal.csv` |
| Evaluation capture: 221 windows and the attack log | `data/eval.csv`, `data/attack_log.csv` |
| Overhead benchmark: naive per-event tracer vs. in-kernel tracer | `bench.py`, `ebpf/naive_tracer.py`, `data/bench.jsonl` |
| Per-attack detection delay and unshare analysis | `analyze.py` |
| Live demo watcher: prints NORMAL / ALERT for each window | `demo/watch.py` |
| Handoff and status notes | `docs/naman_handoff_2026-09-22.md` |

**Key findings:**
- Per-event export costs 72.8% of nginx throughput (3.7× slowdown, 3.9× p50 latency).
- The in-kernel tracer's overhead is below the measurement noise on the VM.

### Pending

| Item | Why it matters | Priority |
|---|---|---|
| Run the `unshare` check in the demo container | "Operation not permitted" confirms seccomp. "Command not found" means ns_escape never ran, and the results must be redone without it | 🔴 Before submission |
| Rerun all 3 benchmark conditions in one session, confirming the naive tracer is attached each time, and append the results to `bench.jsonl` | One naive run (1022 rps) was faster than no tracing. It stays in the raw data, and the paper explains why it was excluded | 🟠 Before Review 3 |
| Measure distinct and total syscalls per window | Requested for the paper | 🟡 Planned |
| Syscall-pair (bigram) counting and `stat_01`–`stat_03` | Not for Review 3: adding them would invalidate the model and every result | ⚪ Future work |
| Overhead on bare metal | The VM varies by about ±14% between runs | ⚪ Future work |

---

## Krishita: data pipeline and integration (Member 2)

**Owns:** `member2/`, `tests/`, the CSV contract, README and docs, the repository

### Done

| Work | Where |
|---|---|
| CSV contract agreed with Naman: 77 columns, row rules, metadata types | `docs/naman_krishita_csv_contract.md` |
| Feature schema: one column list shared by the tracer, validator and model | `member2/schema.py` |
| 6-stage pipeline: load → validate → map columns → separate metadata → build `X` | `member2/` |
| Mock data generator for development before real data existed | `member2/mock_aggregated_csv.py` |
| Real-data integration: Naman's CSV passes with no code changes | `member2/pipeline.py` |
| Stricter validation for the resolved rules (`cgroup_id` type, statistic ranges) | `member2/validation.py` |
| Evaluation labelling from the attack log, including attacks that cross a window boundary | `member2/evaluation_labels.py` |
| Single-window preparation for the live demo (`prepare_window`) | `member2/pipeline.py` |
| Model integration: `score_window`, `anomaly_threshold` and the evaluation script | `person3_ml/detect.py`, `person3_ml/evaluate.py` |
| 18 automated tests (18/18 pass), including a sample of real data | `tests/` |
| README with architecture, contract, schema and handoff docs | `README.md`, `docs/` |
| Independent check of all evaluation and benchmark numbers against the data | All paper values match |
| Threshold sensitivity analysis and baselines (Isolation Forest, One-Class SVM) | Results shared with the team (not committed) |
| Repository maintenance and merging both integration PRs | PR #1, PR #2 |

### Pending

| Item | Priority |
|---|---|
| If the unshare check says "command not found": use the prepared results that exclude window 90 (220 windows, TP 7, FP 8, TN 201, FN 4, precision 0.467, recall 0.636, FPR 0.038, 4/4 attacks) | 🔴 Only if needed |
| Rename placeholder columns (`pair_37_count`, etc.) to readable names (team decision) | ⚪ Future work |

---

## Abhiram: anomaly model (Member 3)

**Owns:** `person3_ml/` (model, training, detection, plots)

### Done

| Work | Where |
|---|---|
| Autoencoder: 74 → 64 → 32 → 8 → 32 → 64 → 74 | `person3_ml/autoencoder.py` |
| Scaler fitted on normal training data only | `person3_ml/preprocessing.py` |
| Training: 100 epochs, 503 training / 125 validation windows, seed 42 | `person3_ml/train.py` |
| Trained model, scaler and threshold (95th percentile = 0.0015323) | `person3_ml/models/` |
| Batch detection script | `person3_ml/detect.py` |
| Training-loss and reconstruction-error plots | `person3_ml/plot_results.py`, `person3_ml/results/` |

**Key numbers:**
- Final training loss 0.000270, validation loss 0.000323.
- Scoring takes about 0.14 ms per window.

### Pending

| Item | Why it matters | Priority |
|---|---|---|
| Decide the threshold | The 95th percentile flags about 4% of normal windows (about 1 false ALERT every 26 s in the demo). The 99th percentile or mean + 3σ would cut FPR to 0.014 with the same recall | 🟠 Before demo |
| Note library versions | The scaler was saved with scikit-learn 1.9.1, and the results reproduce exactly with 1.6.1 | 🟡 For the paper |
| Retrain if bigrams are added later | The current model only fits the 21-feature data | ⚪ Future work |

---

## Team decisions

| Decision | Outcome |
|---|---|
| Bigrams before Review 3? | **No.** The paper reports a 74-dimensional input with 21 populated features. Bigrams are designed but not evaluated. |
| Headline threshold | **95th percentile.** Other thresholds appear only as sensitivity analysis, since they were checked after seeing the eval results. |
| Demo false alerts | **Explain upfront** if one appears: about 4% of normal windows are flagged at this threshold. |

## Demo checklist

1. `docker run -d --name demo nginx`
2. Terminal 1: `python3 demo/watch.py data/live.csv`. It waits for the file;
   start it first so it doesn't replay old rows all at once.
3. Terminal 2: `sudo python3 ebpf/tracer.py demo data/live.csv`. Wait for the
   watcher to print the threshold.
4. Terminal 3: `python3 workload/normal_traffic.py demo 600`
5. Trigger an attack, e.g. `bash workload/attack.sh demo`. Expect an ALERT
   within about 1 s.
