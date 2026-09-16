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
| `cgroup_id` | Identifier of the container/cgroup the row belongs to | integer or string (exact type TBD — see dependency below) |
| `window_start_ns` | Start of the aggregation window, nanoseconds since an agreed epoch | integer (int64) |
| `window_end_ns` | End of the aggregation window, nanoseconds since the same epoch | integer (int64) |

Constraints:
- `window_end_ns > window_start_ns` strictly, for every row.
- Both timestamps use the same clock/epoch for every row in the file
  (e.g., consistently `CLOCK_MONOTONIC` boot time, or consistently
  epoch-based — **which one is a pending decision from Naman**, tracked as
  a dependency below).
- Metadata columns are carried alongside the model input as context but are
  **never** passed to the autoencoder.

**Open dependency (Naman):** the exact type/format of `cgroup_id` (numeric
cgroup inode ID vs. a string container name/hash) and the clock/epoch basis
for the two `*_ns` fields are not yet confirmed. Do not assume either until
Naman specifies it — the mock CSV generator (Task 4+) will pick a
placeholder convention and flag it as such.

## 5. Feature columns (74 total)

Per the agreed architecture (not yet agreed: the names):

| Group | Count | Expected dtype |
|---|---|---|
| Syscall / unigram counts | 20 | non-negative integer (int64) |
| Syscall-pair / bigram counts | 50 | non-negative integer (int64) |
| Aggregate statistics | 4 | numeric — integer or float, **pending definition** |

Constraints:
- Count columns (unigram + bigram, 70 of the 74) must be non-negative
  integers. A negative count is invalid input.
- The 4 aggregate-statistic columns' valid ranges/types cannot be
  constrained yet because their definitions are undefined — this is an
  **open dependency (Naman/Abhiram)**. Once defined (e.g., mean syscall
  duration, unique-syscall ratio, etc.), this section should be updated
  with real constraints (e.g., ratios in `[0, 1]`, non-negative durations).
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
- Labels for anomaly evaluation datasets — if/when a labeled evaluation CSV
  exists, it is expected to carry an additional label column beyond these
  77, kept separate from the 74 model features (see Member 2 responsibility
  #9). Not otherwise specified here since no labeled dataset exists yet.

## Open dependencies tracked in this document

- [ ] Real syscall/pair/stat column names and order (Naman + Abhiram).
- [ ] Definition and valid range of each of the 4 aggregate statistics
      (Naman/Abhiram).
- [ ] `cgroup_id` representation: numeric vs. string.
- [ ] Clock/epoch basis for `window_start_ns` / `window_end_ns`.

Until these are resolved, the mock CSV generator (upcoming task) will
adopt explicit, clearly-labeled placeholder conventions consistent with
this contract, so the pipeline can be built and tested end-to-end now and
re-pointed at Naman's real CSV later without code changes.
