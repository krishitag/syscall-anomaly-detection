#!/usr/bin/env python3
"""Review 3: confusion matrices for data/eval.csv and each eval run.

For every (eval_csv, attack_log) pair it reports, against the same
overlap-based window labels Member 2's pipeline uses:

  (a) the autoencoder          -- person3_ml.detect, err > anomaly_threshold()
  (b) a security-family rule   -- flag any window where any of
        execve, clone, connect, socket, setns, unshare, ptrace,
        fchmodat, fchownat, kill  has a non-zero count

plus, per attack, whether each detector fired and its detection delay.

usage: python3 bench/eval_confusion.py [eval_csv attack_log] ...
       (no args -> data/eval.csv + data/attack_log.csv, then eval_run{1,2,3})
"""
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import numpy as np

from member2.evaluation_labels import prepare_labeled_evaluation
from person3_ml.detect import reconstruction_errors, anomaly_threshold

# Security-relevant families -> their syscall_NN_count column (see ebpf/vocab.py).
SEC = {
    "execve": "syscall_08_count",
    "clone": "syscall_10_count",
    "connect": "syscall_11_count",
    "socket": "syscall_13_count",
    "setns": "syscall_14_count",
    "unshare": "syscall_15_count",
    "ptrace": "syscall_16_count",
    "fchmodat": "syscall_17_count",
    "fchownat": "syscall_18_count",
    "kill": "syscall_19_count",
}


def confusion(pred, y):
    pred = pred.astype(bool)
    y = y.astype(bool)
    tp = int((pred & y).sum())
    fp = int((pred & ~y).sum())
    tn = int((~pred & ~y).sum())
    fn = int((~pred & y).sum())
    prec = tp / (tp + fp) if (tp + fp) else 0.0
    rec = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0
    return dict(tp=tp, fp=fp, tn=tn, fn=fn, prec=prec, rec=rec, f1=f1, fpr=fpr)


def print_cm(name, cm):
    print(
        f"  {name:14s} TP={cm['tp']:3d} FP={cm['fp']:3d} TN={cm['tn']:3d} FN={cm['fn']:3d}"
        f"   P={cm['prec']:.4f} R={cm['rec']:.4f} F1={cm['f1']:.4f} FPR={cm['fpr']:.4f}"
    )


def analyze(eval_csv, attack_log):
    labeled = prepare_labeled_evaluation(eval_csv, attack_log)
    prepared, y, attacks = labeled.prepared, labeled.y, labeled.attacks

    errs = reconstruction_errors(prepared.X)
    th = anomaly_threshold()
    ae_pred = (errs > th).astype(int)

    # Rule prediction, read straight from the raw CSV in row order.
    rows = list(csv.DictReader(open(eval_csv)))
    assert len(rows) == len(y), f"{eval_csv}: {len(rows)} rows vs {len(y)} labels"
    starts = np.array([int(r["window_start_ns"]) for r in rows], dtype=np.int64)
    ends = np.array([int(r["window_end_ns"]) for r in rows], dtype=np.int64)
    rule_pred = np.array(
        [1 if any(int(r[c] or 0) for c in SEC.values()) else 0 for r in rows],
        dtype=int,
    )

    n_attack = int(y.sum())
    print(f"\n{'=' * 78}")
    print(f"{eval_csv}  +  {attack_log}")
    print(
        f"{'=' * 78}\nwindows={len(y)}  attack-windows={n_attack}  normal={len(y) - n_attack}"
        f"  threshold={th:.7f}  attacks={len(attacks)}"
    )

    print("\nconfusion matrices (vs overlap labels):")
    ae_cm = confusion(ae_pred, y)
    rule_cm = confusion(rule_pred, y)
    print_cm("autoencoder", ae_cm)
    print_cm("security-rule", rule_cm)

    def delay(pred, s):
        for i in range(len(rows)):
            if ends[i] >= s and pred[i]:
                return (ends[i] - s) / 1e9
        return None

    print("\nper attack:")
    print(f"  {'attack':16s} {'win':>3s}  {'AE':>8s} {'delay':>9s}   {'RULE':>8s} {'delay':>9s}")
    for a in attacks:
        ov = (a.start_ns < ends) & (a.end_ns >= starts)
        idx = np.where(ov)[0]
        ae_hit = bool(ae_pred[idx].any()) if len(idx) else False
        rule_hit = bool(rule_pred[idx].any()) if len(idx) else False
        ae_d = delay(ae_pred, a.start_ns)
        rule_d = delay(rule_pred, a.start_ns)
        print(
            f"  {a.attack:16s} {len(idx):3d}  {'HIT' if ae_hit else 'miss':>8s} "
            f"{('%.2fs' % ae_d) if ae_d is not None else '-':>9s}   "
            f"{'HIT' if rule_hit else 'miss':>8s} "
            f"{('%.2fs' % rule_d) if rule_d is not None else '-':>9s}"
        )

    ae_det = sum(
        1 for a in attacks
        if ae_pred[np.where((a.start_ns < ends) & (a.end_ns >= starts))[0]].any()
    )
    rule_det = sum(
        1 for a in attacks
        if rule_pred[np.where((a.start_ns < ends) & (a.end_ns >= starts))[0]].any()
    )
    print(f"\n  attacks detected: autoencoder {ae_det}/{len(attacks)}   rule {rule_det}/{len(attacks)}")
    return ae_cm, rule_cm, ae_det, rule_det, len(attacks)


def main():
    pairs = []
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        pairs = [(args[i], args[i + 1]) for i in range(0, len(args), 2)]
    else:
        pairs = [("data/eval.csv", "data/attack_log.csv")]
        for i in (1, 2, 3):
            e, a = f"data/eval_run{i}.csv", f"data/attack_log_run{i}.csv"
            if os.path.exists(e) and os.path.exists(a):
                pairs.append((e, a))
            else:
                print(f"(skipping run {i}: {e} / {a} not present yet)")

    results = []
    for eval_csv, attack_log in pairs:
        results.append((eval_csv, analyze(eval_csv, attack_log)))

    if len(results) > 1:
        print(f"\n{'=' * 78}\nPOOLED across all captures\n{'=' * 78}")
        ae = dict(tp=0, fp=0, tn=0, fn=0)
        rule = dict(tp=0, fp=0, tn=0, fn=0)
        ae_det = rule_det = n_at = 0
        for _, (ae_cm, rule_cm, aed, rd, na) in results:
            for k in ae:
                ae[k] += ae_cm[k]
                rule[k] += rule_cm[k]
            ae_det += aed
            rule_det += rd
            n_at += na

        def finalize(c):
            c = dict(c)
            c["prec"] = c["tp"] / (c["tp"] + c["fp"]) if (c["tp"] + c["fp"]) else 0.0
            c["rec"] = c["tp"] / (c["tp"] + c["fn"]) if (c["tp"] + c["fn"]) else 0.0
            c["f1"] = (
                2 * c["prec"] * c["rec"] / (c["prec"] + c["rec"])
                if (c["prec"] + c["rec"]) else 0.0
            )
            c["fpr"] = c["fp"] / (c["fp"] + c["tn"]) if (c["fp"] + c["tn"]) else 0.0
            return c

        print_cm("autoencoder", finalize(ae))
        print_cm("security-rule", finalize(rule))
        print(f"\n  attacks detected (pooled): autoencoder {ae_det}/{n_at}   rule {rule_det}/{n_at}")


if __name__ == "__main__":
    main()
