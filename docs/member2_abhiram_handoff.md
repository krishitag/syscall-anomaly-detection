# Member 2 -> Abhiram model-input handoff

Member 2 receives Naman's **already-aggregated** container-window CSV and
prepares the input for Abhiram's autoencoder. No raw syscall events are read,
counted, paired, or windowed in this stage.

## Use this interface

For an ordinary (unlabelled) Naman-format CSV, use the stable Member 2 entry
point:

```python
from member2.pipeline import prepare_aggregated_csv

prepared = prepare_aggregated_csv("path/to/naman_aggregated.csv")

X = prepared.X
feature_columns = prepared.feature_columns
metadata_columns = prepared.metadata_columns
metadata_rows = prepared.metadata_rows
```

`prepare_aggregated_csv` loads, validates, maps columns by name to the
canonical order, separates metadata, and creates the model matrix. It accepts
the Task 4 mock CSV and Naman's later real CSV through the same function,
provided the CSV follows the established contract.

## What Abhiram receives

| Value | Type / shape | Use |
|---|---|---|
| `X` | NumPy `float64`, shape `(n_rows, 74)` | The only input for the autoencoder |
| `feature_columns` | tuple of 74 strings | Exact column meaning/order for `X[:, i]` |
| `metadata_rows` | tuple of `n_rows` tuples, each width 3 | Context to attach to results, never model input |
| `metadata_columns` | `("cgroup_id", "window_start_ns", "window_end_ns")` | Names for the metadata tuple fields |

Row alignment is guaranteed: `X[i]` describes the same container/time window
as `metadata_rows[i]`.

```text
X[i]                     -> 74 numeric behavior features for one window
metadata_rows[i]         -> (cgroup_id, window_start_ns, window_end_ns)
```

The metadata values are kept in their CSV text representation. In the current
mock fixture, `cgroup_id` is a placeholder numeric-looking string and the
timestamps use a synthetic origin. Do not treat either convention as Naman's
final choice.

## Feature order and current dependencies

The 74 feature positions always follow `member2.schema.FEATURE_COLUMNS`:

1. 20 syscall/unigram count columns
2. 50 syscall-pair/bigram count columns
3. 4 aggregate-statistic columns

The names currently in `member2/schema.py` are placeholders. The team must
replace the four schema column lists with Naman's agreed real vocabulary and
stat definitions before interpreting a model feature by name. The matrix shape
and the handoff interface remain `(n_rows, 74)`.

Pending team decisions that Member 2 does not infer:

- Real syscall and pair feature names/order
- Definitions and valid ranges of the four statistics
- `cgroup_id` representation
- Timestamp clock/epoch basis

## Labels and results

Normal Naman deliveries have exactly 77 columns and no label. If a future
evaluation dataset has one additional label column, Member 2's
`separate_evaluation_labels` utility removes a caller-specified label column
before the normal 77-column path. Its label vector remains separate from `X`.

Abhiram owns the autoencoder, reconstruction error, threshold selection,
normal/anomaly classification, and evaluation. Member 2 does not produce or
claim anomaly results, metrics, or rates.
