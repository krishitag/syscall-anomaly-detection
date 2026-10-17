# Handoff → Abhiram: retraining required after collection-layer changes

**From:** Naman (Member 1, eBPF collection)
**Date:** 2026-10-17
**Short version:** I'm changing the feature vector and the windowing. The current model,
scaler and threshold will be invalid against the new data. You'll need a full retrain, and
every number currently in the paper changes.

---

## 1. What is changing

| Change | Before | After |
|---|---|---|
| Bigram features (`pair_01..50_count`) | all zero | **real counts** of consecutive syscall pairs |
| Windowing | fixed 1 s, non-overlapping | **sliding: 2 s span, emitted every 1 s** |
| Live features | 21 of 74 | **71 of 74** |
| `stat_01`, `stat_02`, `stat_03` | zero | still zero (not implemented) |

Unchanged: the 77-column CSV format, column names, `member2` contract, the 20-syscall
vocabulary and its family grouping.

### Why this invalidates the current model

1. **Scaler.** Fitted on data where 50 columns were constant zero. Those columns now carry
   real counts, often larger than the unigram values. Any scaler fitted on the old data will
   mis-scale them.
2. **Threshold.** Reconstruction error is computed over all 74 dimensions. With 50 previously
   dead dimensions now active, the error distribution shifts entirely. `0.001532` is
   meaningless against new data.
3. **Windowing.** Rows now overlap, and each covers 2 s rather than 1 s. Counts roughly
   double, independent of the bigram change.

**Do not score new captures with the current artifacts.** It will run and produce numbers;
they will be garbage.

---

## 2. What you'll receive

- `data/normal.csv` — fresh capture, varied nginx traffic, training set
- `data/eval.csv` — fresh capture, background traffic + 5 attacks
- `data/attack_log.csv` — attack intervals (epoch ns), for labelling
- `docs/VOCAB.md` — updated, including the index→pair mapping for columns 20–69

The previous unigram-era captures are preserved as `data/normal_unigram.csv` and
`data/eval_unigram.csv` so the old results stay reproducible.

---

## 3. What I need back

### 3.1 Retrain
Same architecture, refit on the new `normal.csv`:
- scaler refitted on new normal data only
- autoencoder retrained
- threshold recomputed on new normal data only
- `eval.csv` must not touch training, scaling or thresholding

### 3.2 Threshold — please change the rule

Current threshold is the **95th percentile of validation reconstruction error**, which flags
~5% of normal windows *by construction*. That is why precision came out at 0.500 (8 TP, 8 FP)
— it's an artifact of the rule, not a property of the model, and it's the weakest-looking
number in the paper.

Please report, on the new data:
- the operating point under `mean + 3×std` (the original plan)
- a **precision–recall curve** or ROC across thresholds, so the paper reports a curve rather
  than one arbitrary operating point

That one change is likely the single biggest improvement to how the results read.

### 3.3 Numbers for the paper

Krishita asked for these and they're still outstanding:

1. Full evaluation output: TP, FP, TN, FN, precision, recall, F1, FPR, threshold used
2. Per attack: how many of its windows were flagged
3. **Mean and max reconstruction error on attack windows vs normal windows**, and the ratio
   between them (a line like "attack windows scored N× higher" is strong in the paper)
4. Final training and validation loss (last epoch)
5. **Scoring time per window in milliseconds** — needed to claim real-time detection
6. Any alternative threshold or baseline detector you tried (Isolation Forest, One-Class SVM),
   even rough numbers. A non-deep baseline on identical features would strengthen the
   evaluation section considerably.

### 3.4 Keep working per-window scoring

`demo/watch.py` imports `score_window(x)` and `anomaly_threshold()` from `person3_ml.detect`.
The live demo depends on both. Please keep those signatures.

---

## 4. Things about the new data to expect

- **Rows overlap.** Consecutive rows share one second of data. For autoencoder training this
  is acceptable, but it means rows are not independent samples — worth a sentence in the
  paper, and worth knowing if you do any train/validation splitting (**split by time, not
  randomly**, or adjacent overlapping rows will leak between the splits).
- **Bigram columns will be sparse but not zero.** Most of the 50 pairs will be zero in any
  given window; a handful dominate.
- **Scale mismatch.** Bigram counts are comparable to unigram counts in magnitude; `stat_04`
  is bounded 0–20; `stat_01`–`stat_03` are still constant zero. **Constant-zero columns break
  hand-written standardisation** — `(x - mean) / std` divides by zero. Use a scaler that
  handles zero variance.
- **More attack windows per attack**, because of the overlap, so the TP/FP balance shifts
  relative to the old results.

---

## 5. Timing

I'll push the new captures once the tracer changes are done and verified. Everything in §3
is blocked on your retrain, and the paper's evaluation section is blocked on §3.3.

Conference deadline is 31 Oct; Review 3 needs the paper plus a working demo.
