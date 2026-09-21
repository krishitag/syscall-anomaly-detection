"""The 20-syscall vocabulary. Order is locked: index 0 -> syscall_01_count."""
from bcc.syscall import syscalls  # {nr: b"name"} for this machine

VOCAB_NAMES = [
    "read", "write", "recvfrom", "openat", "close",
    "mmap", "munmap", "execve", "epoll_wait", "clone",
    "connect", "accept4", "socket", "setns", "unshare",
    "ptrace", "fchmodat", "fchownat", "kill", "sendfile",
]

NAME_TO_NR = {v.decode(): k for k, v in syscalls.items()}
VOCAB_NRS = [NAME_TO_NR[n] for n in VOCAB_NAMES]
NR_TO_INDEX = {nr: i for i, nr in enumerate(VOCAB_NRS)}

assert len(VOCAB_NAMES) == 20 and len(set(VOCAB_NRS)) == 20

if __name__ == "__main__":
    for i, (name, nr) in enumerate(zip(VOCAB_NAMES, VOCAB_NRS), 1):
        print(f"syscall_{i:02d}_count  {name:12s} nr={nr}")