#!/usr/bin/env python3
"""Pick the 50 emitted pair columns from a survey capture."""
import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vocab import VOCAB_NAMES

SURVEY = sys.argv[1] if len(sys.argv) > 1 else "data/pair_survey.json"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pairs.json")
N = 50

# Hand-picked fallback transitions: process-startup and payload-staging
# sequences that plausibly occur during post-exploitation but were absent
# from the baseline survey. Ordered by expected relevance.
IDX = {n: i for i, n in enumerate(VOCAB_NAMES)}
FALLBACK = [
    ("clone", "execve"), ("execve", "openat"), ("execve", "mmap"),
    ("execve", "read"), ("execve", "close"), ("execve", "write"),
    ("openat", "fchmodat"), ("openat", "fchownat"), ("fchmodat", "openat"),
    ("read", "openat"), ("openat", "openat"), ("openat", "close"),
    ("socket", "close"), ("connect", "write"), ("connect", "read"),
    ("write", "write"), ("clone", "clone"), ("clone", "close"),
    ("kill", "kill"), ("execve", "execve"), ("mmap", "openat"),
    ("munmap", "mmap"), ("close", "clone"), ("read", "mmap"),
    ("write", "openat"),
]

survey = {tuple(int(x) for x in k.split(",")): v
          for k, v in json.load(open(SURVEY)).items()}
observed = sorted(survey.items(), key=lambda kv: -kv[1])

chosen = [p for p, _ in observed][:N]
print(f"observed {len(observed)} distinct pairs; taking {len(chosen)}")

extra = [(IDX[a], IDX[b]) for a, b in FALLBACK
         if (IDX[a], IDX[b]) not in set(chosen)]
need = N - len(chosen)
chosen += extra[:need]
print(f"padded with {min(need, len(extra))} hand-picked transitions")

assert len(chosen) == N, f"only {len(chosen)} pairs available, need {N}"
assert len(set(chosen)) == N, "duplicate pair in selection"
json.dump([list(p) for p in chosen], open(OUT, "w"))

print(f"\nwrote {OUT}")
for k, (i, j) in enumerate(chosen, 1):
    c = survey.get((i, j), 0)
    tag = "" if c else "   [unobserved]"
    print(f"  pair_{k:02d}_count  {VOCAB_NAMES[i]}->{VOCAB_NAMES[j]:12s} {c}{tag}")