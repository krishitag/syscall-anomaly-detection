"""
Feature schema contract for the syscall anomaly detection pipeline.

STATUS: PLACEHOLDER NAMES.

The column GROUPING and COUNTS below (20 syscall counts + 50 pair counts +
4 aggregate stats = 74 feature columns, plus 3 metadata columns = 77 total)
are fixed per the team's agreed architecture.

The actual NAMES are not yet finalized -- they depend on:
  - which 20 syscalls Naman's eBPF program tracks
  - which 50 syscall pairs Naman's eBPF program tracks
  - what the 4 aggregate statistics are defined to be

Do not invent real names here. Once the team finalizes them, update the four
lists below (SYSCALL_COUNT_COLUMNS, PAIR_COUNT_COLUMNS, STAT_COLUMNS,
METADATA_COLUMNS) in place. Every downstream module (loader, validator,
mapper) imports column lists from this file rather than hardcoding names, so
that update should not require changes anywhere else.
"""

# --- Metadata columns (kept separately, NOT fed to the autoencoder) ---
METADATA_COLUMNS = [
    "cgroup_id",
    "window_start_ns",
    "window_end_ns",
]

# --- Feature columns (fed to the autoencoder, in this exact order) ---

# 20 syscall / unigram count features. PLACEHOLDER NAMES.
SYSCALL_COUNT_COLUMNS = [f"syscall_{i:02d}_count" for i in range(1, 21)]

# 50 syscall-pair / bigram count features. PLACEHOLDER NAMES.
PAIR_COUNT_COLUMNS = [f"pair_{i:02d}_count" for i in range(1, 51)]

# 4 aggregate statistics. PLACEHOLDER NAMES.
STAT_COLUMNS = [f"stat_{i:02d}" for i in range(1, 5)]

# The 74 columns handed to Abhiram's autoencoder, in fixed order.
FEATURE_COLUMNS = SYSCALL_COUNT_COLUMNS + PAIR_COUNT_COLUMNS + STAT_COLUMNS

# All 77 columns expected in Naman's aggregated CSV.
ALL_COLUMNS = METADATA_COLUMNS + FEATURE_COLUMNS

# Self-check: fail loudly at import time if a future edit breaks the contract.
assert len(METADATA_COLUMNS) == 3, "expected exactly 3 metadata columns"
assert len(SYSCALL_COUNT_COLUMNS) == 20, "expected exactly 20 syscall-count columns"
assert len(PAIR_COUNT_COLUMNS) == 50, "expected exactly 50 pair-count columns"
assert len(STAT_COLUMNS) == 4, "expected exactly 4 aggregate-stat columns"
assert len(FEATURE_COLUMNS) == 74, "expected exactly 74 feature columns"
assert len(ALL_COLUMNS) == 77, "expected exactly 77 total columns"
assert len(set(ALL_COLUMNS)) == 77, "duplicate column name detected"


if __name__ == "__main__":
    print(f"metadata columns : {len(METADATA_COLUMNS)} -> {METADATA_COLUMNS}")
    print(f"syscall columns  : {len(SYSCALL_COUNT_COLUMNS)} -> {SYSCALL_COUNT_COLUMNS[:3]} ...")
    print(f"pair columns     : {len(PAIR_COUNT_COLUMNS)} -> {PAIR_COUNT_COLUMNS[:3]} ...")
    print(f"stat columns     : {len(STAT_COLUMNS)} -> {STAT_COLUMNS}")
    print(f"total feature cols (-> Abhiram): {len(FEATURE_COLUMNS)}")
    print(f"total columns (Naman CSV)      : {len(ALL_COLUMNS)}")
    print("Schema self-check passed.")
