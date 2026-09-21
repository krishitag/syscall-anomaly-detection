"""
20-column syscall vocabulary. Order is locked: index 0 -> syscall_01_count.

Each column counts a FAMILY of equivalent syscalls, so the column moves
no matter which variant libc happens to use (open vs openat, clone vs clone3...).
"""
from bcc.syscall import syscalls  # {nr: b"name"} for this machine

VOCAB = [
    ("read",       ["read"]),
    ("write",      ["write"]),
    ("recvfrom",   ["recvfrom"]),
    ("openat",     ["open", "openat", "openat2", "creat"]),
    ("close",      ["close"]),
    ("mmap",       ["mmap"]),
    ("munmap",     ["munmap"]),
    ("execve",     ["execve", "execveat"]),
    ("epoll_wait", ["epoll_wait", "epoll_pwait", "epoll_pwait2"]),
    ("clone",      ["clone", "clone3", "fork", "vfork"]),
    ("connect",    ["connect"]),
    ("accept4",    ["accept", "accept4"]),
    ("socket",     ["socket"]),
    ("setns",      ["setns"]),
    ("unshare",    ["unshare"]),
    ("ptrace",     ["ptrace"]),
    ("fchmodat",   ["chmod", "fchmod", "fchmodat", "fchmodat2"]),
    ("fchownat",   ["chown", "lchown", "fchown", "fchownat"]),
    ("kill",       ["kill", "tkill", "tgkill"]),
    ("sendfile",   ["sendfile"]),
]

NAME_TO_NR = {v.decode(): k for k, v in syscalls.items()}
VOCAB_NAMES = [label for label, _ in VOCAB]

NR_TO_INDEX = {}
SKIPPED = []
for i, (label, family) in enumerate(VOCAB):
    found = [n for n in family if n in NAME_TO_NR]
    SKIPPED += [n for n in family if n not in NAME_TO_NR]
    assert found, f"column {label}: no syscall in its family exists here"
    for n in found:
        NR_TO_INDEX[NAME_TO_NR[n]] = i

assert len(VOCAB) == 20

if __name__ == "__main__":
    for i, (label, family) in enumerate(VOCAB, 1):
        members = [f"{n}={NAME_TO_NR[n]}" for n in family if n in NAME_TO_NR]
        print(f"syscall_{i:02d}_count  {label:11s} {', '.join(members)}")
    if SKIPPED:
        print(f"\nnot in this machine's syscall table (skipped): {SKIPPED}")