# Naman -> Krishita CSV Contract

This document defines the interface between Naman's in-kernel/eBPF
aggregation output and Member 2's (Krishita's) pipeline. It specifies the
**shape and format** of the handoff, not the final feature vocabulary — see
[member2_feature_schema.md](member2_feature_schema.md) for column-name
status and [`member2/schema.py`](../member2/schema.py) for the authoritative
column list.

This contract exists so Naman's real CSV can later replace the mock CSV
without any changes to downstream Member 2 code, as long as both sides
honor what's written here.

## 1. Delivery format

- One `.csv` file per handoff (or per batch), UTF-8 encoded, comma-delimited.
- The file **must** have a header row as its first line.
- Standard CSV quoting/escaping rules apply (RFC 4180). No embedded raw
  newlines inside fields.

## 2. Header requirements

- The header must contain **exactly** the column names defined in
  `member2.schema.ALL_COLUMNS` (currently the placeholder set: 3 metadata +
  74 feature columns = 77 total) — no more, no fewer.
- Column names are matched **by name, case-sensitive**, not by position.
  Krishita's loader will look up columns by name and reorder them into the
  canonical order from `schema.py`. This means Naman's CSV does **not**
  need to emit columns in the exact schema order — but every expected name
  must be present exactly once, and no unexpected extra columns should be
  present (an unexpected column is treated as a contract violation, not
  silently ignored, since it may indicate a schema drift that both sides
  need to resync on).
- Header names are placeholders until the team finalizes the real syscall /
  pair / stat vocabulary (see open dependency in
  [member2_feature_schema.md](member2_feature_schema.md)). When that
  happens, this contract's *rules* stay the same — only the concrete names
  in `schema.py` change.

## 3. Row semantics: one row per (container, window)

- Each row represents **one already-aggregated observation**: a single
  container (`cgroup_id`) over a single, already-closed time window
  (`window_start_ns` .. `window_end_ns`).
- The pair `(cgroup_id, window_start_ns)` (equivalently, `(cgroup_id,
  window_end_ns)`) **must be unique** across the file — no duplicate rows
  for the same container+window.
- Krishita's pipeline does not merge, split, re-window, or otherwise
  aggregate rows. Aggregation is entirely Naman's responsibility, performed
  in-kernel before the CSV is produced. If two rows describe overlapping or
  duplicate windows for the same container, that is treated as an invalid
  input, not something the pipeline resolves.
- Rows for different containers may be interleaved in any order; the
  pipeline does not assume the file is sorted by container or by time.

## 4. Metadata columns

| Column | Meaning | Expected dtype |
|---|---|---|
| `cgroup_id` | Identifier of the container/cgroup the row belongs to (cgroup v2 inode number) | integer (int64) |
| `window_start_ns` | Start of the aggregation window, nanoseconds since an agreed epoch | integer (int64) |
| `window_end_ns` | End of the aggregation window, nanoseconds since the same epoch | integer (int64) |

Constraints:
- `window_end_ns > window_start_ns` strictly, for every row.
- Both timestamps use the same clock for every row in the file: Unix-epoch
  nanoseconds from `time.time_ns()`.
- Metadata columns are carried alongside the model input as context but are
  **never** passed to the autoencoder.

**Resolved (Naman, [VOCAB.md](VOCAB.md) §1–2):** `cgroup_id` is the numeric
cgroup v2 inode ID from `bpf_get_current_cgroup_id()`, written as int64. It
changes when a container restarts. Both `*_ns` fields are Unix-epoch
nanoseconds.

## 5. Feature columns (74 total)

Per the agreed architecture (not yet agreed: the names):

| Group | Count | Expected dtype |
|---|---|---|
| Syscall / unigram counts | 20 | non-negative integer (int64) |
| Syscall-pair / bigram counts | 50 | non-negative integer (int64) |
| Aggregate statistics | 4 | see table below |

The 4 statistics, as defined in [VOCAB.md](VOCAB.md) §3:

| Column | Meaning | Type | Valid range |
|---|---|---|---|
| `stat_01` | Mean inter-arrival time between consecutive syscalls in the window, in ns | float | `>= 0.0` |
| `stat_02` | Standard deviation (not variance) of the same inter-arrival times, in ns | float | `>= 0.0` |
| `stat_03` | Count of syscalls in the window that returned an error | int | `>= 0` |
| `stat_04` | Number of distinct syscalls from the 20-syscall vocabulary seen in the window | int | `0 <= x <= 20` |

Constraints:
- Count columns (unigram + bigram, 70 of the 74) must be non-negative
  integers. A negative count is invalid input.
- The 4 aggregate-statistic columns must fall within the ranges above.
  When a window has fewer than two syscalls, `stat_01` and `stat_02` are
  written as `0.0`, never blank.
- No column in the 74 feature columns may contain nulls/NaN/empty string in
  a well-formed row. A missing value for a given window means that
  window's count is genuinely zero and should be written as `0`, not left
  blank — blank/NaN is treated as a validity error, not an implicit zero.

## 6. Basic data validity expectations (summary)

A row is well-formed if all of the following hold:
1. All 77 expected columns are present (by name), no unexpected columns.
2. No nulls/NaN/blank fields in any of the 77 columns.
3. `window_end_ns > window_start_ns`.
4. All 70 count-feature values are non-negative integers.
5. `cgroup_id` is non-empty and consistent in type across all rows.
6. No duplicate `(cgroup_id, window_start_ns)` pairs in the file.

These are the checks Task 5 (validation) will implement against real or
mock data. This document only defines what "valid" means; it does not
implement enforcement.

## 7. What this contract deliberately does NOT cover

- The real names/order of the 20 syscall, 50 pair, and 4 stat columns —
  tracked in [member2_feature_schema.md](member2_feature_schema.md).
- How Naman's eBPF program computes counts or picks window boundaries —
  that's entirely inside Member 1's scope and out of bounds for this
  document.
- Labels for anomaly evaluation datasets. The evaluation CSV uses these same
  77 columns; labels come from a separate `attack_log.csv`
  (`attack,start_ns,end_ns`, same Unix-epoch ns clock), and
  `member2.evaluation_labels.prepare_labeled_evaluation` joins the two.

## Open dependencies tracked in this document

- [x] Meaning and order of the 20 syscall columns — locked in
      [VOCAB.md](VOCAB.md) §4. Column names in `schema.py` stay as placeholders.
- [ ] Index-to-pair mapping for the 50 pair columns (Naman) — deferred per
      [VOCAB.md](VOCAB.md) §5. Pair columns are all 0 until then.
- [x] Definition and valid range of each of the 4 aggregate statistics —
      [VOCAB.md](VOCAB.md) §3 (see §5 above).
- [x] `cgroup_id` representation: numeric (int64 cgroup inode ID).
- [x] Clock/epoch basis for `window_start_ns` / `window_end_ns`: Unix-epoch ns.

Naman's real CSV (`data/normal.csv`, 628 rows) passes this pipeline without
code changes. The mock CSV generator is kept for tests only.
