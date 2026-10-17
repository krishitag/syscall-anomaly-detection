# VOCAB.md — Feature Vocabulary & Resolved Schema Dependencies

**Owner:** Naman Bhatia (24BDS0056), Member 1 (eBPF / in-kernel aggregation)
**Last updated:** 2026-10-17 (bigrams and sliding windows)
**Companion to:** `member2/schema.py` (authoritative column list — names unchanged by this document)

---

## 0. What this document does and does not change

**Does not change:** column count (77), column names (`member2/schema.py` placeholders stand),
column grouping, or any rule in the CSV contract.

**Does define:** what each placeholder column *means*, so that `syscall_07_count` and
`pair_12_count` have an agreed referent on both sides of the handoff.

Renaming placeholder columns to human-readable names is deferred (see §7).

---

## 1. Resolved dependency: `cgroup_id` representation

**Decision: integer (int64).**

Obtained from `bpf_get_current_cgroup_id()`, which returns the **inode number of the
container's cgroup v2 directory** under
`/sys/fs/cgroup/system.slice/docker-<container_id>.scope`. It is a `u64` in the kernel, but
observed values are small (e.g. `11242`), so int64 is safe.

**Note for Member 2:** this value is *not stable across container restarts*. A recreated
container gets a new cgroup directory and a new inode. It identifies a container only within
one capture run.

---

## 2. Resolved dependency: clock / epoch basis

**Decision: epoch nanoseconds (UTC), stamped in userspace.**

`window_start_ns` and `window_end_ns` are produced by the userspace poller using Python's
`time.time_ns()`.

Rationale: window boundaries are defined by the poller, not the kernel — the eBPF program has
no concept of a window. Epoch time was chosen over `CLOCK_MONOTONIC` because monotonic values
reset at boot and cannot be correlated with container start times, logs, or the labelled
attack timeline used for evaluation.

The kernel-side `bpf_ktime_get_ns()` (monotonic) would be used internally for inter-arrival
*durations*; durations are clock-basis independent, so this does not conflict.

---

## 3. Resolved dependency: the 4 aggregate statistics

| Column | Meaning | dtype | Valid range | Implemented |
|---|---|---|---|---|
| `stat_01` | Mean inter-arrival time between consecutive syscalls, ns | float | `>= 0.0` | **No — always 0.0** |
| `stat_02` | **Standard deviation** of the same inter-arrival times, ns | float | `>= 0.0` | **No — always 0.0** |
| `stat_03` | Count of syscalls in the window returning an error (`sys_exit` with `ret < 0`) | int | `>= 0` | **No — always 0** |
| `stat_04` | Number of distinct syscalls from the 20-syscall vocabulary observed in the window | int | `0 <= x <= 20` | Yes |

### Note on `stat_02` — standard deviation, not variance

Earlier internal notes specified *variance*. This document specifies **standard deviation**,
deliberately. Variance of nanosecond gaps is in ns², producing values in the 10^12–10^18
range while count columns sit in the tens or hundreds. Under MSE loss that single column
would dominate reconstruction error entirely. Standard deviation carries the same information
in nanoseconds, on a scale comparable to `stat_01`.

Input normalisation is still required regardless.

### Edge cases

- A window with fewer than 2 syscalls has no inter-arrival gap. `stat_01` and `stat_02` are
  written as `0.0`, never blank (contract §5: blank/NaN is a validity error).
- `stat_04` counts vocabulary syscalls only.

---

## 4. Syscall vocabulary — columns `syscall_01_count` .. `syscall_20_count`

Index order is **locked**. Syscall numbers are **x86_64**; the mapping is
architecture-specific and would differ on ARM64.

Each column counts a **family** of equivalent syscalls, so the feature responds regardless of
which variant the C library selects. Families group only true variants of the same operation,
never distinct operations.

| Column | Family label | Members |
|---|---|---|
| `syscall_01_count` | `read` | read |
| `syscall_02_count` | `write` | write |
| `syscall_03_count` | `recvfrom` | recvfrom |
| `syscall_04_count` | `openat` | open, openat, openat2, creat |
| `syscall_05_count` | `close` | close |
| `syscall_06_count` | `mmap` | mmap |
| `syscall_07_count` | `munmap` | munmap |
| `syscall_08_count` | `execve` | execve, execveat |
| `syscall_09_count` | `epoll_wait` | epoll_wait, epoll_pwait, epoll_pwait2 |
| `syscall_10_count` | `clone` | clone, clone3, fork, vfork |
| `syscall_11_count` | `connect` | connect |
| `syscall_12_count` | `accept4` | accept, accept4 |
| `syscall_13_count` | `socket` | socket |
| `syscall_14_count` | `setns` | setns |
| `syscall_15_count` | `unshare` | unshare |
| `syscall_16_count` | `ptrace` | ptrace |
| `syscall_17_count` | `fchmodat` | chmod, fchmod, fchmodat, fchmodat2 |
| `syscall_18_count` | `fchownat` | chown, lchown, fchown, fchownat |
| `syscall_19_count` | `kill` | kill, tkill, tgkill |
| `syscall_20_count` | `sendfile` | sendfile |

Syscall numbers are resolved at runtime from BCC's syscall table (`ebpf/vocab.py`), so a typo
fails immediately rather than silently counting the wrong call, and the numbers are always
correct for the running kernel.

### Why families: calls named in prior work never fire

The vocabulary was revised after inspecting real traces. Contemporary glibc routes `open` to
`openat`, `accept` to `accept4`, `fork` to `clone`, and `chmod` to `fchmodat` — all distinct
syscall numbers. Counting the named call alone yields a permanently-zero feature. Three of the
ten security-relevant columns would otherwise have been blind to the evaluated attacks.

### Purpose split

- **Normal-behaviour syscalls** give the model a baseline: `read`, `write`, `recvfrom`,
  `openat`, `close`, `mmap`, `munmap`, `epoll_wait`, `accept4`, `sendfile`.
- **Security-relevant syscalls** stay near zero normally and spike under attack: `execve`,
  `clone`, `connect`, `socket`, `setns`, `unshare`, `ptrace`, `fchmodat`, `fchownat`, `kill`.

### Known limitation: seccomp-blocked syscalls are invisible

`unshare` recorded **0 occurrences across all 221 windows** of the evaluation capture.
Confirmed directly:

```
$ docker exec demo unshare --user --map-root-user true; echo "exit=$?"
unshare: unshare failed: Operation not permitted
exit=1
```

Docker's default seccomp profile rejects the call **before the `sys_enter` tracepoint
executes**, so the attempt produces no observable signal. The `ns_escape` attack was still
flagged, but via `execve`/`clone` from the `docker exec` wrapper rather than its signature
syscall. This is a limitation of tracepoint-based collection generally, not of this
implementation, and belongs in the paper's limitations section.

---

## 5. Syscall pair vocabulary — columns `pair_01_count` .. `pair_50_count`

**Status: locked 2026-10-17.**

### How the 50 were chosen

The eBPF program counts **all 400 ordered vocabulary transitions** (20 × 20) in kernel space.
A 400-entry per-cgroup map costs the same single increment per event as a 50-entry map, so
there is no collection-overhead difference. The userspace poller emits 50 of them as columns.

A baseline survey capture (nginx traffic plus the 5 simulated attacks) observed only **33
distinct vocabulary transitions** — nginx's request loop is highly regular, so the transition
space is small. The 50 columns are therefore:

- **Columns 1–33:** every transition observed in the survey, ordered by frequency.
- **Columns 34–50:** 17 hand-picked process-startup and payload-staging transitions that are
  plausible during post-exploitation but were absent from the survey.

Columns 1–6 reconstruct nginx's request loop directly from kernel data:
`epoll_wait → recvfrom → openat → sendfile → write → close`.

| Column | Transition | Survey count |
|---|---|---|
| `pair_01_count` | write → close | 306 |
| `pair_02_count` | epoll_wait → recvfrom | 300 |
| `pair_03_count` | close → epoll_wait | 300 |
| `pair_04_count` | epoll_wait → accept4 | 296 |
| `pair_05_count` | close → close | 267 |
| `pair_06_count` | sendfile → write | 228 |
| `pair_07_count` | recvfrom → openat | 131 |
| `pair_08_count` | mmap → mmap | 87 |
| `pair_09_count` | read → read | 35 |
| `pair_10_count` | mmap → close | 34 |
| `pair_11_count` | close → openat | 32 |
| `pair_12_count` | openat → read | 25 |
| `pair_13_count` | read → close | 17 |
| `pair_14_count` | close → mmap | 11 |
| `pair_15_count` | connect → close | 10 |
| `pair_16_count` | socket → connect | 10 |
| `pair_17_count` | close → socket | 7 |
| `pair_18_count` | close → write | 4 |
| `pair_19_count` | mmap → munmap | 3 |
| `pair_20_count` | read → epoll_wait | 2 |
| `pair_21_count` | close → read | 2 |
| `pair_22_count` | write → recvfrom | 2 |
| `pair_23_count` | epoll_wait → epoll_wait | 2 |
| `pair_24_count` | openat → mmap | 1 |
| `pair_25_count` | read → munmap | 1 |
| `pair_26_count` | munmap → close | 1 |
| `pair_27_count` | mmap → read | 1 |
| `pair_28_count` | read → write | 1 |
| `pair_29_count` | write → read | 1 |
| `pair_30_count` | epoll_wait → read | 1 |
| `pair_31_count` | fchmodat → close | 1 |
| `pair_32_count` | fchownat → close | 1 |
| `pair_33_count` | munmap → munmap | 1 |
| `pair_34_count` | clone → execve | 0 (hand-picked) |
| `pair_35_count` | execve → openat | 0 (hand-picked) |
| `pair_36_count` | execve → mmap | 0 (hand-picked) |
| `pair_37_count` | execve → read | 0 (hand-picked) |
| `pair_38_count` | execve → close | 0 (hand-picked) |
| `pair_39_count` | execve → write | 0 (hand-picked) |
| `pair_40_count` | openat → fchmodat | 0 (hand-picked) |
| `pair_41_count` | openat → fchownat | 0 (hand-picked) |
| `pair_42_count` | fchmodat → openat | 0 (hand-picked) |
| `pair_43_count` | read → openat | 0 (hand-picked) |
| `pair_44_count` | openat → openat | 0 (hand-picked) |
| `pair_45_count` | openat → close | 0 (hand-picked) |
| `pair_46_count` | socket → close | 0 (hand-picked) |
| `pair_47_count` | connect → write | 0 (hand-picked) |
| `pair_48_count` | connect → read | 0 (hand-picked) |
| `pair_49_count` | write → write | 0 (hand-picked) |
| `pair_50_count` | clone → clone | 0 (hand-picked) |

The authoritative mapping is `ebpf/pairs.json`, regenerable with `ebpf/pick_pairs.py` from a
survey capture.

### Known limitation: thread-keyed transitions

Bigrams are tracked **per thread** (the `last_sc` scratch map is keyed by tid), so a
transition is recorded only when both calls occur in the same thread. This correctly prevents
interleaved nginx workers from manufacturing spurious pairs, but it means `clone → execve` —
the canonical process-spawn transition — is never observed, because `clone` returns in the
parent thread while `execve` runs in the child. Fork/exec sequences are captured by the
unigram counts only.

### Observed discriminative power

Normal nginx traffic shows ~7 distinct active pair columns per window. Attack windows showed
19–27. The pair count alone separates attack from normal, independently of the unigrams.

---

## 6. Windowing

**As of 2026-10-17, windows slide.** Each row covers a **2-second span**, and a row is emitted
every **1 second**. Consecutive rows overlap by one second.

Rationale: with fixed non-overlapping windows, an attack straddling a boundary left a trailing
window containing only its tail, which closely resembled normal traffic. This was the cause of
the false negatives in the pre-17-Oct evaluation. With overlap, any attack shorter than the
span falls entirely within at least one window.

**Consequence for modelling:** rows are **not independent samples**. A train/validation split
must be made **by time**, not randomly, or adjacent overlapping rows leak across the split and
validation loss is artificially low.

Counts are computed by **differencing snapshots** — kernel counters are never cleared, so no
event is lost in the gap between reading and resetting.

---

## 7. Still open

- [ ] **`stat_01`–`stat_03`** (inter-arrival mean/std, error count) — not implemented; require
      a `sys_exit` hook and per-thread timestamp tracking. 3 of 74 columns remain constant zero.
- [ ] **Renaming placeholder columns** to readable names (team decision) — required before the
      report, where `pair_37_count` is not a usable label. Isolated to `member2/schema.py` and
      this document.

---

## 8. Changelog

| Date | Change |
|---|---|
| 2026-09-20 | Initial version. Resolved `cgroup_id` type, clock basis, and the 4 aggregate statistics. Locked the 20-syscall vocabulary order. Deferred the 50-pair mapping. |
| 2026-09-21 | Revised 6 vocabulary slots after the first real capture (03 → recvfrom, 09 → epoll_wait, 12 → accept4, 17 → fchmodat, 18 → fchownat, 20 → sendfile). Introduced syscall families. |
| 2026-10-17 | Locked the 50-pair mapping from a survey capture. Switched to sliding 2 s / 1 s windows. Confirmed seccomp blocks `unshare` before the tracepoint. Documented the thread-keying limitation on `clone → execve`. |
