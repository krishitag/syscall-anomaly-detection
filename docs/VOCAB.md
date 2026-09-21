# VOCAB.md — Feature Vocabulary & Resolved Schema Dependencies

**Owner:** Naman Bhatia (24BDS0056), Member 1 (eBPF / in-kernel aggregation)
**Status:** Resolves 3 of the 4 open dependencies in `docs/naman_krishita_csv_contract.md`.
**Companion to:** `member2/schema.py` (authoritative column list — names unchanged by this document)

---

## 0. What this document does and does not change

**Does not change:** column count (77), column names (`member2/schema.py` placeholders stand),
column grouping, or any rule in the CSV contract. Member 2's loader, validator and tests
require no changes as a result of this document.

**Does define:** what each placeholder column *means*, so that `syscall_07_count` has an
agreed referent on both sides of the handoff.

Renaming placeholder columns to human-readable names is deferred (see §5).

---

## 1. Resolved dependency: `cgroup_id` representation

**Decision: integer (int64).**

The eBPF program obtains this from `bpf_get_current_cgroup_id()`, which returns the
**inode number of the container's cgroup v2 directory** under
`/sys/fs/cgroup/system.slice/docker-<container_id>.scope`. It is a `u64` in the kernel,
but observed values on the target environment are small (example: `11758`), so int64 is
safe and no string encoding is needed.

**Note for Member 2:** this value is *not stable across container restarts*. A recreated
container gets a new cgroup directory and therefore a new id. Do not treat `cgroup_id` as a
persistent container identity across separate capture runs; it identifies a container only
within one run.

---

## 2. Resolved dependency: clock / epoch basis

**Decision: epoch nanoseconds (UTC), stamped in userspace.**

`window_start_ns` and `window_end_ns` are produced by the userspace poller using Python's
`time.time_ns()` — nanoseconds since the Unix epoch.

Rationale: window boundaries are defined by the poller, not by the kernel — the eBPF program
has no concept of a window. Epoch time was chosen over `CLOCK_MONOTONIC` because monotonic
values reset at boot and cannot be correlated with container start times, logs, or the
labelled attack timeline used for evaluation.

The kernel-side `bpf_ktime_get_ns()` (monotonic) is used internally to compute inter-arrival
*durations* for the stat columns. Durations are clock-basis independent, so this does not
conflict with the above.

---

## 3. Resolved dependency: the 4 aggregate statistics

| Column | Meaning | dtype | Valid range |
|---|---|---|---|
| `stat_01` | Mean inter-arrival time between consecutive syscalls, in nanoseconds, for this cgroup within this window | float | `>= 0.0` |
| `stat_02` | **Standard deviation** of the same inter-arrival times, in nanoseconds | float | `>= 0.0` |
| `stat_03` | Count of syscalls in this window returning an error (`sys_exit` with `ret < 0`) | int | `>= 0` |
| `stat_04` | Number of distinct syscalls **from the 20-syscall vocabulary** observed in this window | int | `0 <= x <= 20` |

### Note on `stat_02` — standard deviation, not variance

Earlier internal notes specified *variance*. This document specifies **standard deviation**
instead, deliberately.

Variance of nanosecond gaps is expressed in ns², producing values in the 10^12–10^18 range,
while every count column sits in the tens or hundreds. Under the autoencoder's MSE loss that
single column would dominate the reconstruction error almost entirely and the other 73
features would contribute effectively nothing. Standard deviation carries the same
information in nanoseconds, on a scale comparable to `stat_01`.

**Abhiram:** input normalisation is still required regardless of this change — `stat_01` and
`stat_02` remain orders of magnitude larger than the count columns.

### Edge cases

- A window with fewer than 2 syscalls has no inter-arrival gap to measure.
  `stat_01` and `stat_02` are written as `0.0` in that case, never blank
  (per contract §5: blank/NaN is a validity error).
- `stat_04` counts vocabulary syscalls only. Syscalls outside the 20-syscall vocabulary are
  not counted anywhere in the feature vector.

---

## 4. Syscall vocabulary — columns `syscall_01_count` .. `syscall_20_count`

Index order is **locked**. Do not reorder; downstream column meaning depends on position.

Syscall numbers are **x86_64**. This mapping is architecture-specific and would differ on
ARM64.

| Column | Syscall | x86_64 nr |
|---|---|---|
| `syscall_01_count` | `read` | 0 |
| `syscall_02_count` | `write` | 1 |
| `syscall_03_count` | `recvfrom` | 45 |
| `syscall_04_count` | `openat` | 257 |
| `syscall_05_count` | `close` | 3 |
| `syscall_06_count` | `mmap` | 9 |
| `syscall_07_count` | `munmap` | 11 |
| `syscall_08_count` | `execve` | 59 |
| `syscall_09_count` | `epoll_wait` | 232 |
| `syscall_10_count` | `clone` | 56 |
| `syscall_11_count` | `connect` | 42 |
| `syscall_12_count` | `accept4` | 288 |
| `syscall_13_count` | `socket` | 41 |
| `syscall_14_count` | `setns` | 308 |
| `syscall_15_count` | `unshare` | 272 |
| `syscall_16_count` | `ptrace` | 101 |
| `syscall_17_count` | `fchmodat` | 268 |
| `syscall_18_count` | `fchownat` | 260 |
| `syscall_19_count` | `kill` | 62 |
| `syscall_20_count` | `sendfile` | 40 |

**Revised 2026-09-21** after the first filtered capture of the nginx demo container. Six slots
changed, all in place (same column, new syscall):

| Slot | Was | Now | Reason |
|---|---|---|---|
| 03 | `open` | `recvfrom` | `open` never fires on modern glibc; nginx reads requests with `recvfrom` (2 per request) |
| 09 | `fork` | `epoll_wait` | `fork` is implemented via `clone`; `epoll_wait` is nginx's event loop (3 per request) |
| 12 | `accept` | `accept4` | confirmed: nginx called `accept4` 200 times for 200 requests, `accept` zero times |
| 17 | `chmod` | `fchmodat` | coreutils `chmod` issues `fchmodat`, not `chmod` — would have hidden the demo attack |
| 18 | `chown` | `fchownat` | same reason as `chmod` |
| 20 | `getpid` | `sendfile` | `getpid` carries no signal; `sendfile` is nginx's response-body path (1 per request) |

The resulting vocabulary is split by purpose: normal-behaviour syscalls (`read`, `write`,
`recvfrom`, `openat`, `close`, `mmap`, `munmap`, `epoll_wait`, `accept4`, `sendfile`) give the
autoencoder a real baseline to learn, and security-relevant syscalls (`execve`, `clone`,
`connect`, `socket`, `setns`, `unshare`, `ptrace`, `fchmodat`, `fchownat`, `kill`) stay near zero
normally and spike under attack. Column count and names are unchanged; Member 2 code is
unaffected.

Syscall numbers above are to be verified against the target kernel before the tracer is
considered correct:

```
grep -E '__NR_(read|write|open|openat|close|mmap|munmap|execve|fork|clone|connect|accept|socket|setns|unshare|ptrace|chmod|chown|kill|getpid) ' \
  /usr/include/x86_64-linux-gnu/asm/unistd_64.h
```

### Known risk: several vocabulary entries may never fire

Modern glibc routes some of these calls through newer variants that are **distinct syscall
numbers** and therefore will not increment the columns above:

| Vocabulary entry | Likely actually used | Consequence |
|---|---|---|
| `open` (2) | `openat` (257) | `syscall_03_count` likely always 0 |
| `accept` (43) | `accept4` (288) | `syscall_12_count` likely always 0 |
| `fork` (57) | `clone` (56) | `syscall_09_count` likely always 0 |

A column that is constant zero across every row contributes nothing to the autoencoder — it
is reconstructed perfectly and carries no signal, effectively reducing the feature vector
below 74 usable dimensions.

**This is to be confirmed empirically**, not assumed: once the tracer runs against the demo
container, check which of the 20 columns are non-zero. If the three above are indeed dead,
the recommended fix is to substitute `accept4`, drop `open`/`fork` in favour of more active
syscalls, and record the substitution here. Column count and names are unaffected by such a
substitution — only this table changes.

---

## 5. Syscall pair vocabulary — columns `pair_01_count` .. `pair_50_count`

**Status: index→pair mapping deliberately deferred. Column count and names are final.**

### Approach

The eBPF program tracks **all 400 ordered pairs** (20 × 20) of the vocabulary above, not 50.
A 400-entry per-cgroup map costs the same single increment per syscall event as a 50-entry
map would — the per-event work is identical, only the array being indexed is larger. There is
no measurable collection-overhead difference, which matters because collection overhead is
this project's novelty claim.

The **userspace poller** then selects which 50 of the 400 tracked pairs are emitted as CSV
columns.

### Why this is deferred rather than guessed

Selecting 50 pairs before any traffic has been observed means choosing arbitrarily, which is
not defensible in the report. Selecting after a baseline capture allows the selection to be
stated as a method: *"the 50 pairs were selected from all 400 observed transitions in
baseline container traffic."*

### Planned selection policy

- **40 pairs** — highest-frequency transitions observed in baseline (normal) container traffic.
- **10 pairs** — hand-selected security-relevant transitions that are rare in normal traffic
  but expected during anomalous behaviour (e.g. transitions involving `execve`, `ptrace`,
  `setns`, `unshare`, or `connect` following process creation).

Pure top-50-by-frequency is avoided because it selects exclusively for normal behaviour, and
some transitions most indicative of an intrusion are rare by construction.

Once the baseline capture exists, the resulting index→pair table is appended to this document
and the selection is then locked.

### Impact on Member 2: none

`PAIR_COUNT_COLUMNS` in `member2/schema.py` remains `pair_01_count` .. `pair_50_count`.
The loader, validator, mapper and tests are unaffected by which transitions those 50 indices
ultimately refer to.

---

## 6. Still open

- [ ] **Index→pair mapping for the 50 pair columns** (Naman) — deferred per §5, resolved after
      baseline capture.
- [ ] **Empirical confirmation of dead vocabulary columns** (Naman) — per §4, checked on first
      real capture.
- [ ] **Renaming placeholder columns to human-readable names** (team) — optional. Deferred
      until after integration, since it requires a coordinated change on both sides for no
      functional gain. Required before the report, where `pair_37_count` is not a usable
      label. Isolated to `member2/schema.py` and this document.

---

## 7. Changelog

| Date | Change |
|---|---|
| 2026-09-20 | Initial version. Resolves `cgroup_id` type, clock basis, and the 4 aggregate statistics. Locks the 20-syscall vocabulary order. Defers the 50-pair index mapping with a stated selection policy. |
