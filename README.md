# syscall-anomaly-detection
System Call Anomaly Detection System for Docker Containers using eBPF and Autoencoders

## Current integration status

The pipeline runs end to end on real kernel data:

```
nginx container → eBPF tracer (ebpf/) → 77-column CSV (data/normal.csv)
                → member2.prepare_aggregated_csv() → X (N × 74)
                → Autoencoder (person3_ml/) → reconstruction error vs. threshold
```

- **Member 1 (collection):** `ebpf/tracer.py` traces one container by cgroup
  and writes one row per 1-second window in the agreed 77-column format.
  `data/normal.csv` holds 628 windows from 10 minutes of nginx traffic
  (`workload/normal_traffic.py`). Simulated attacks are in `workload/attack.sh`.
- **Member 2 (CSV preparation):** `data/normal.csv` passes through
  `prepare_aggregated_csv()` with no code changes, producing a `(628, 74)`
  feature matrix. The mock CSV generator remains only for tests.
- **Member 3 (model):** `person3_ml/` trains an autoencoder on the prepared
  features. The trained model, scaler and threshold are saved in
  `person3_ml/models/`, and training plots are in `person3_ml/results/`.

### What is real in the 74 features

| Columns | Status |
|---|---|
| `syscall_01..20_count` | Real unigram counts; each column counts one syscall family |
| `stat_04` | Real: distinct vocabulary syscalls in the window (0–20) |
| `pair_01..50_count` | Always 0 (bigram counting is deferred to the final review) |
| `stat_01..03` | Always 0 (timing mean/std and error count are deferred to the final review) |

Column names in `member2/schema.py` are unchanged placeholders.
[`docs/VOCAB.md`](docs/VOCAB.md) defines what each column means, including
the `cgroup_id` type, the timestamp clock and the 4 statistics.

### Still open

- Index-to-pair mapping for the 50 pair columns (Member 1).
- Evaluation capture: `data/eval.csv` plus `data/attack_log.csv` (Member 1).
  Member 2's `prepare_labeled_evaluation()` already turns them into `X` and
  0/1 labels.
- Live demo loop (Member 1): tracer row → `member2.pipeline.prepare_window()`
  → the model's per-window score → alert.
- Renaming placeholder columns to readable names before the final report.

See [the Review 2 artifact overview](docs/review2_intermediate_artifacts.md)
for the full architecture, [the CSV contract](docs/naman_krishita_csv_contract.md)
for the Naman-to-Krishita handoff requirements, and
[Naman's handoff notes](docs/naman_handoff_2026-09-22.md) for the latest
Member 1 status.
