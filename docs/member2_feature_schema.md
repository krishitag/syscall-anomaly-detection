# Feature Schema (Member 2)

Defined in [`member2/schema.py`](../member2/schema.py). This is the single
source of truth for column names and order — every later Member 2 module
(loader, validator, mapper) imports from it instead of hardcoding names.

## Status: placeholder names, confirmed structure

The structure is fixed by the team's agreed architecture:

| Group | Count | Fed to autoencoder? |
|---|---|---|
| Metadata (`cgroup_id`, `window_start_ns`, `window_end_ns`) | 3 | No — kept separately as context |
| Syscall / unigram counts | 20 | Yes |
| Syscall-pair / bigram counts | 50 | Yes |
| Aggregate statistics | 4 | Yes |
| **Total feature columns -> Abhiram** | **74** | |
| **Total columns in Naman's CSV** | **77** | |

The actual names (`syscall_01_count`, `pair_07_count`, `stat_02`, etc.) are
**placeholders**. They are not invented feature definitions — they exist only
so the pipeline can be built and tested end-to-end before the real
vocabulary is available.

## Unresolved, pending the team

- The exact 20 syscalls Naman's eBPF program counts.
- The exact 50 syscall pairs Naman's eBPF program counts.
- The exact definition of each of the 4 aggregate statistics.

## Update procedure once finalized

Edit the four column lists at the top of `member2/schema.py` in place, in
the same fixed order the team agrees on. No other file should need to
change — loader, validator, and mapper all consume `FEATURE_COLUMNS`,
`METADATA_COLUMNS`, and `ALL_COLUMNS` from this module.
