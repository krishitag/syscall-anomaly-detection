# Review 2: intermediate artifacts and architecture

This document records the runnable intermediate artifacts available for Review
2. It intentionally reports no anomaly results, accuracy, threshold, or
anomaly rate: those require Member 3's model and a real/evaluation dataset.

## Complete system architecture

```mermaid
flowchart LR
    subgraph M1[Member 1 — Naman: collection and in-kernel aggregation]
        C[Docker container] --> S[System calls]
        S --> P[eBPF syscall probes]
        P --> A[In-kernel aggregation\ncounts, pairs, window statistics]
        A --> B[BPF maps]
        B --> E[CSV exporter]
        E --> R[Aggregated CSV\n1 row per container + closed window\n77 columns]
    end

    subgraph M2[Member 2 — Krishita: data/interface pipeline]
        F[Task 4 mock aggregated CSV\ndevelopment fixture only] -.same 77-column contract.-> L
        R --> L[Load raw CSV]
        L --> V[Validate CSV contract]
        V --> O[Map columns by name\nto canonical schema order]
        O --> D[Separate 3 metadata fields\nfrom 74 feature fields]
        D --> X[X matrix\nshape: n rows × 74\ndtype: float64]
        D --> M[Metadata/context\n(cgroup_id, window start, window end)]
        Q[Optional evaluation label column] --> QL[Keep labels separate]
        QL -.unlabelled 77-column data.-> V
    end

    subgraph M3[Member 3 — Abhiram: anomaly model and evaluation]
        X --> AE[Autoencoder]
        AE --> RE[Reconstruction error]
        RE --> T[Threshold]
        T --> CL[Normal / anomaly classification]
        CL --> J[Join classification with metadata]
        M --> J
        J --> OUT[Results and evaluation output]
    end
```

### How outputs are generated

1. Naman's eBPF side aggregates events inside the kernel before the CSV is
   written. Member 2 does not receive or recreate individual syscall events.
2. Every CSV row is one completed `(cgroup_id, time window)` observation:
   3 metadata columns plus 74 numeric behavior features.
3. Member 2 validates and orders these fields, emitting `X` for the model and
   parallel metadata for interpreting any later model output.
4. Abhiram's model produces reconstruction errors and classifications. Those
   classifications are associated back to container/time context using aligned
   metadata rows.

## Runnable Review 2 artifacts

The following commands produce and verify actual Member 2 intermediate data:

```bash
# Produce 6 already-aggregated mock observations (2 containers × 3 windows).
python3 -m member2.mock_aggregated_csv /private/tmp/review2_mock.csv

# Verify the contract, mapping, feature split, and X handoff via the test suite.
python3 -m unittest discover -s tests -v

# Inspect the model-ready handoff shape.
python3 -c 'from member2.pipeline import prepare_aggregated_csv; p = prepare_aggregated_csv("/private/tmp/review2_mock.csv"); print(p.X.shape, p.X.dtype, len(p.metadata_rows))'
```

Expected final command output for this example is a `(6, 74)` `float64` matrix
and 6 aligned metadata rows. This is a structural pipeline demonstration, not
a detection result.

| Artifact | Review 2 evidence |
|---|---|
| `member2/schema.py` | Single source of truth for 3 metadata + 74 feature columns |
| `member2/mock_aggregated_csv.py` | Reproducible already-aggregated mock CSV generator |
| `member2/csv_loader.py` and `member2/validation.py` | Raw delivery handling and contract enforcement |
| `member2/column_mapping.py` and `member2/feature_separation.py` | Name-based canonical ordering and model/context split |
| `member2/model_input.py` and `member2/pipeline.py` | Model-ready `float64` X handoff with stable CSV-path interface |
| `member2/evaluation_labels.py` | Evaluation labels remain outside the model feature matrix |
| `tests/test_member2_pipeline.py` | Automated integration evidence |
| `docs/member2_abhiram_handoff.md` | Member 3 interface specification |

## Review status and remaining dependencies

Member 2's rough-draft data/interface path is implemented and testable with
the mock contract fixture. The complete project diagram above is the agreed
integration design; implementation/results status for Member 1 and Member 3
must be supplied by those members for a team-level "75% complete" claim.

Before a real end-to-end result can be reported, the team still needs:

- Naman's real 20 syscall names, 50 pair names, and four statistic definitions
- The real `cgroup_id` representation and timestamp clock/epoch convention
- Naman's contract-compliant eBPF-generated CSV
- Abhiram's autoencoder, threshold procedure, and evaluation dataset/results

When the real feature vocabulary is agreed, Member 2 updates the four column
lists in `member2/schema.py`; the downstream Member 2 modules import those
lists rather than hardcoding names.
