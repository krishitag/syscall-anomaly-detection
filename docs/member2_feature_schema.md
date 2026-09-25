# Feature Schema (Member 2)

Defined in [`member2/schema.py`](../member2/schema.py). This is the single
source of truth for column names and order — every later Member 2 module
(loader, validator, mapper) imports from it instead of hardcoding names.

## Status: placeholder names, defined meanings

The structure is fixed by the team's agreed architecture:

| Group | Count | Fed to autoencoder? |
|---|---|---|
| Metadata (`cgroup_id`, `window_start_ns`, `window_end_ns`) | 3 | No — kept separately as context |
| Syscall / unigram counts | 20 | Yes |
| Syscall-pair / bigram counts | 50 | Yes |
| Aggregate statistics | 4 | Yes |
| **Total feature columns -> Abhiram** | **74** | |
| **Total columns in Naman's CSV** | **77** | |

The names (`syscall_01_count`, `pair_07_count`, `stat_02`, etc.) are still
**placeholders**, but [VOCAB.md](VOCAB.md) now defines what each one means:

- **Syscall columns:** the 20-syscall vocabulary and its order are locked
  (VOCAB.md §4). Each column counts a family of equivalent syscalls.
- **Statistics:** all 4 are defined, with valid ranges (VOCAB.md §3).
  `validate_aggregated_csv` enforces those ranges.
- **Pair columns:** the index-to-pair mapping is still open (VOCAB.md §5).
  Naman's tracer writes 0 for all 50 until bigram counting is added.

## Renaming to readable names (optional)

Readable names are needed before the report, where `pair_37_count` is not a
usable label. To rename, edit the four column lists at the top of
`member2/schema.py` in place. Naman's `ebpf/tracer.py` writes its header from
the same lists, so both sides stay in sync. No other Member 2 file should need
to change.
