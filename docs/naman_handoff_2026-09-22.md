# Member 1 (Naman) — Status & Handoff

**As of:** Tue 2026-09-22, 01:50 IST  **Review 2:** Wed (working demo)

---

## 1. Where things stand

The collection layer is working end to end on real kernel data:

```
nginx container → eBPF tracer (in-kernel counting) → 77-column CSV
                → Krishita's prepare_aggregated_csv() → X (N × 74) → Abhiram's model
```

- `ebpf/tracer.py` traces one container by cgroup, emits one row per 1-second window.
- Output passes Krishita's pipeline unmodified: `prepare_aggregated_csv()` accepts it.
- **`data/normal.csv` captured:** 10 min of varied nginx traffic → **628 windows × 74 features**, validated.
- `docs/VOCAB.md` defines what every column means and resolves 3 of the 4 contract dependencies.

## 2. What is real in the 74 columns (and what isn't yet)

| Columns | Status |
|---|---|
| `syscall_01..20_count` | **real** — unigram counts |
| `stat_04` | **real** — number of distinct vocab syscalls in the window (0–20) |
| `pair_01..50_count` | **all 0** — bigrams not implemented yet (final review) |
| `stat_01`, `stat_02`, `stat_03` | **all 0** — timing mean/std and error count not implemented yet (final review) |

So 54 of 74 columns are constant zero in current data. Fine for the review-2 demo; the attacks
are caught by the unigrams alone.

## 3. Things about the real data that differ from synthetic data

- **Vocabulary changed** (see `docs/VOCAB.md`). Six slots now mean different syscalls:
  03 recvfrom, 09 epoll_wait, 12 accept4, 17 fchmodat, 18 fchownat, 20 sendfile.
  Each column also counts a *family* of equivalent syscalls (e.g. column 10 = clone + clone3 +
  fork + vfork). Column names are unchanged.
- **Idle windows are all zeros.** Many rows in `normal.csv` are fully zero. That is real normal
  behaviour, not missing data.
- **Scale varies a lot.** Normal rows range from 0 to a few hundred per column; attack rows
  push columns like `mmap`, `openat`, `close` into the 20–80 range from a near-zero baseline.
- **Attacks can split across two windows** when they straddle a 1-second boundary. One attack
  may produce two anomalous rows.
- **Simulated attacks use `docker exec`**, whose runtime adds its own syscalls (`kill` via
  thread signalling, plus others outside the vocab). Part of each attack signature is
  "docker exec happened." Standard in the literature, but should be stated in the report.
- **`connect`/`socket` also fire on local Unix-socket lookups** (e.g. `id`, `ls -la` resolving
  user names), not only real network connections.

## 4. Krishita — what you can do now

1. **Nothing in your code needs to change.** Real CSV passes as-is.
2. **Update the contract doc** — tick off the 3 dependencies resolved in `docs/VOCAB.md`
   (`cgroup_id` = int64, clock = epoch ns via `time.time_ns()`, the 4 stat definitions).
   Only the 50 pair mappings remain open.
3. **Labels:** is `evaluation_labels.py` meant to attach 0/1 labels to the eval set? If so,
   here is what you'll get from me:
   - `data/eval.csv` — normal traffic + attacks mixed, same 77-column format.
   - `data/attack_log.csv` — `attack,start_ns,end_ns`, one line per attack, same epoch-ns clock.
   - **Rule:** a window is `label = 1` if `[window_start_ns, window_end_ns]` overlaps any
     `[start_ns, end_ns]` interval in the log; otherwise `0`.
   Please confirm this is yours so we don't both write it.
4. **Live demo question:** for the demo, rows arrive one per second while the tracer runs.
   Does your pipeline have (or can it expose) a way to prepare a *single row* into a 74-vector,
   or should the live script reuse `prepare_aggregated_csv` on the growing file? A single-row
   function is cleaner.

## 5. Abhiram — what you can do now

1. **Train on real data:**
   ```python
   from member2.pipeline import prepare_aggregated_csv
   X = prepare_aggregated_csv("data/normal.csv").X   # (628, 74)
   ```
2. **Normalise, and watch the zero columns.** 54 columns are constant zero. Hand-written
   standardisation `(x - mean) / std` divides by zero there and produces NaN. Use a scaler that
   handles zero variance (sklearn's `StandardScaler` does), or `log1p` the counts first.
   Fit the scaler on `normal.csv` only.
3. **`stat_02` is standard deviation, not variance** (reason in `docs/VOCAB.md` §3). Currently 0.
4. **Threshold from `normal.csv` only.** `mean + 3×std` of reconstruction error on training
   data, as planned. `eval.csv` must never be used for training, scaling or threshold-setting —
   otherwise the metrics are inflated.
5. **For the live demo**, the model needs to be usable one window at a time. Please provide:
   - the trained model + fitted scaler saved to disk, and the threshold value;
   - a function like `score_window(x: np.ndarray) -> float` returning reconstruction error
     for one 74-vector.
   I'll write the loop that feeds live windows into it and prints an alert.
6. **Timing:** I need the trained model **by Tue afternoon** so there is time to wire and
   rehearse the live demo before Wednesday.

## 6. My plan for Tuesday

1. **Fix `workload/attack.sh`** (add a 5 s timeout per attack — one attack hung last night) and
   run all 5 attacks uninterrupted. Check whether `unshare` is visible at all: Docker's default
   seccomp profile may block it before the tracepoint fires.
2. **Capture `data/eval.csv`:** tracer + background traffic (different seed from training) +
   `attack.sh` running together, ~3 min. Produces `data/attack_log.csv` alongside.
3. **Labels** — with Krishita's `evaluation_labels.py` if it's hers, otherwise I'll write it.
4. **Live demo loop:** tracer → each new window → model score → `ALERT` line when error
   exceeds threshold. Needs Abhiram's saved model (§5.5).
5. **Rehearse the demo** end to end: start nginx + traffic, trigger an attack live, alert fires.

Stretch, only if all of the above works: bigram counting (task 8).

## 7. Open items

- **Data sharing:** `data/` is gitignored (captures grow fast). I'll send `normal.csv` directly.
  Say if you'd rather have specific sample files force-committed to the repo.
- **Missed review:** status with the faculty guide still unconfirmed.
- **Deferred to final review:** bigrams + remaining stats, overhead measurement (the novelty
  result), vocabulary extension beyond 20.
