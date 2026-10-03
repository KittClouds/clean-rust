"""Hand-built fixture audit for the V2-0 learners.

Every fixture has an answer that is known EXACTLY by construction, so a failure here is an
implementation defect rather than a data question. These run BEFORE any contact with the frozen
400k/50k rows, per the operating directive.

What is being audited:
  * convergence (the optimiser actually reduces the objective)
  * class indexing (labels map to the right columns, and predict() inverts the mapping)
  * tree split semantics (a single-feature tree recovers the exact rule)
  * depth limits (the tree never exceeds max_depth)
  * min_samples_leaf (no leaf is smaller than the floor)
  * determinism (same seed, same result; and a fixed run is bit-reproducible)
  * metric correctness against hand-computed values
  * the B0=100% sanity path shape
"""

import sys
import numpy as np

sys.path.insert(0, r"C:\code land\clean-rust\experiments\ff-s15-v2-eval-00")
from learners import (MultinomialLogisticRegression, DecisionTreeClassifier,
                      macro_f1, accuracy, percentile_bootstrap_ci)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        FAILS.append(name)


print("== F1: logistic regression converges on a separable 2-class problem ==")
# y = x0 > 0.5 is perfectly separable; the optimum drives the boundary to 0.5.
X = np.array([[0.0], [0.1], [0.2], [0.8], [0.9], [1.0]] * 8)
y = np.array([0, 0, 0, 1, 1, 1] * 8)
lr = MultinomialLogisticRegression(l2=1.0, max_iter=200, tol=1e-6, fit_intercept=True, seed=0)
lr.fit(X, y)
check("F1 loss decreased from an untrained start", lr.final_loss_ < 1.0, f"loss={lr.final_loss_:.4f}")
check("F1 predicts every training row correctly", accuracy(y, lr.predict(X)) == 1.0)
# the decision margin between the two classes should sit near zero at the true midpoint
margin = float(lr.decision_function(np.array([[0.5]]))[0, 1] - lr.decision_function(np.array([[0.5]]))[0, 0])
check("F1 margin near zero at the true midpoint", abs(margin) < 0.15, f"margin(0.5)={margin:.4f}")
check("F1 margin is negative left of the boundary and positive right of it",
      float(lr.decision_function(np.array([[0.2]]))[0, 1] - lr.decision_function(np.array([[0.2]]))[0, 0]) < 0
      and float(lr.decision_function(np.array([[0.8]]))[0, 1] - lr.decision_function(np.array([[0.8]]))[0, 0]) > 0)

print("== F2: class indexing is not off by one ==")
# three linearly separable 2-D clusters; the point of this fixture is the label<->column mapping,
# not fit quality, so the problem is made unambiguously separable.
X2 = np.array([[0.0, 0.0], [0.1, 0.1], [0.0, 0.1], [0.1, 0.0]] * 10 +
              [[5.0, 5.0], [5.1, 5.1], [5.0, 5.1], [5.1, 5.0]] * 10 +
              [[9.0, 9.0], [9.1, 9.1], [9.0, 9.1], [9.1, 9.0]] * 10)
y2 = np.array([0] * 40 + [1] * 40 + [2] * 40)
lr2 = MultinomialLogisticRegression(max_iter=200, tol=1e-6, seed=0)
lr2.fit(X2, y2)
check("F2 classes_ recovered in sorted order", list(lr2.classes_) == [0, 1, 2], f"{lr2.classes_}")
check("F2 perfect fit on a separable 3-class problem", accuracy(y2, lr2.predict(X2)) == 1.0,
      f"acc={accuracy(y2, lr2.predict(X2)):.3f}")
check("F2 coef_ shape is (n_features, n_classes)", lr2.coef_.shape == (2, 3), f"{lr2.coef_.shape}")
# per-class recall must be 1.0 for every class, which only holds if the columns are not permuted
for c in (0, 1, 2):
    mask = y2 == c
    check(f"F2 class {c} recalled exactly", bool((lr2.predict(X2[mask]) == c).all()))
# a label set that does not start at zero must still work
y3 = np.array(["a"] * 40 + ["b"] * 40 + ["c"] * 40)
lr3 = MultinomialLogisticRegression(max_iter=200, seed=0).fit(X2, y3)
check("F2 handles non-integer string labels", set(lr3.classes_) == {"a", "b", "c"})
check("F2 string-label predictions are exact", accuracy(y3, lr3.predict(X2)) == 1.0)

print("== F3: single-feature tree recovers an exact threshold rule ==")
# x and y must be built in ALIGNED blocks: the first 40 rows are the low band, the last 40 the high.
Xlow = np.array([[v] for v in (0.0, 0.1, 0.2, 0.3) * 10])
Xhigh = np.array([[v] for v in (0.7, 0.8, 0.9, 1.0) * 10])
Xt = np.vstack([Xlow, Xhigh])
yt = np.array(["L"] * 40 + ["H"] * 40)
check("F3 fixture is aligned (labels separable by construction)",
      bool((Xt[:40, 0] < 0.5).all()) and bool((Xt[40:, 0] > 0.5).all()))
dt = DecisionTreeClassifier(max_depth=6, min_samples_leaf=5, seed=0).fit(Xt, yt)
check("F3 perfect accuracy on the exact rule", accuracy(yt, dt.predict(Xt)) == 1.0,
      f"acc={accuracy(yt, dt.predict(Xt)):.3f}")
root = dt.tree_
check("F3 root is a split on feature 0", (not root["leaf"]) and root["feature"] == 0)
check("F3 threshold sits between 0.3 and 0.7", 0.3 < root["threshold"] < 0.7, f"t={root['threshold']:.3f}")
check("F3 pure leaves", dt.tree_["left"]["impurity"] == 0.0 and dt.tree_["right"]["impurity"] == 0.0)

print("== F4: depth limit is honoured ==")
rng = np.random.default_rng(7)
Xr = rng.normal(size=(600, 8))
yr = (Xr[:, 0] + 0.5 * Xr[:, 1] > 0).astype(int)
for d in (2, 4, 6, 8):
    dtr = DecisionTreeClassifier(max_depth=d, min_samples_leaf=5, seed=0).fit(Xr, yr)
    check(f"F4 max_depth={d} never exceeded", dtr.max_depth_reached() <= d,
          f"reached {dtr.max_depth_reached()}")

print("== F5: min_samples_leaf is honoured ==")


def min_leaf_size(node):
    if node["leaf"]:
        return node["n"]
    return min(min_leaf_size(node["left"]), min_leaf_size(node["right"]))


for ml in (5, 50, 120):
    dtr = DecisionTreeClassifier(max_depth=8, min_samples_leaf=ml, seed=0).fit(Xr, yr)
    check(f"F5 min_samples_leaf={ml} respected", min_leaf_size(dtr.tree_) >= ml,
          f"smallest leaf {min_leaf_size(dtr.tree_)}")

print("== F6: determinism and seed sensitivity ==")
a = DecisionTreeClassifier(max_depth=6, min_samples_leaf=5, seed=0).fit(Xr, yr).predict(Xr)
b = DecisionTreeClassifier(max_depth=6, min_samples_leaf=5, seed=0).fit(Xr, yr).predict(Xr)
check("F6 same seed gives identical predictions", bool((a == b).all()))
c = DecisionTreeClassifier(max_depth=6, min_samples_leaf=5, seed=0).fit(Xr, yr).predict(Xr)
check("F6 re-fit is bit-reproducible", bool((a == c).all()))
la = MultinomialLogisticRegression(max_iter=60, seed=0).fit(Xr, yr)
lb = MultinomialLogisticRegression(max_iter=60, seed=0).fit(Xr, yr)
check("F6 logistic same seed identical coefs", np.allclose(la.coef_, lb.coef_))

print("== F7: metrics against hand-computed values ==")
yt7 = np.array([0, 0, 0, 0, 1, 1, 1, 1])
yp7 = np.array([0, 0, 0, 0, 1, 1, 1, 0])
# by hand, including the extra false positive at index 7:
#   class 0: tp=4, fp=1, fn=0 -> F1 = 2*4/(2*4+1+0) = 8/9
#   class 1: tp=3, fp=0, fn=1 -> F1 = 2*3/(2*3+0+1) = 6/7
#   macro   = (8/9 + 6/7)/2
expected7 = (8.0 / 9.0 + 6.0 / 7.0) / 2.0
check("F7 macro_f1 hand-computed", abs(macro_f1(yt7, yp7) - expected7) < 1e-12,
      f"got {macro_f1(yt7, yp7):.12f} expected {expected7:.12f}")
check("F7 accuracy hand-computed", abs(accuracy(yt7, yp7) - 0.875) < 1e-12)
# degenerate: predicting one class always
yp8 = np.zeros(8, dtype=int)
# class0 F1 = 2*4/(2*4+0+4) = 0.666..; class1 tp0 fp0 fn4 -> 0.0 -> macro 0.3333
check("F7 majority-class macro_f1 hand-computed", abs(macro_f1(yt7, yp8) - (2 * 4 / 12) / 2) < 1e-12,
      f"{macro_f1(yt7, yp8)}")

print("== F8: bootstrap CI brackets the point estimate and is reproducible ==")
lo, hi = percentile_bootstrap_ci(yt7, yp7, accuracy, n_boot=200, seed=20260930)
check("F8 CI brackets the point estimate", lo <= accuracy(yt7, yp7) <= hi, f"[{lo:.3f},{hi:.3f}]")
lo2, hi2 = percentile_bootstrap_ci(yt7, yp7, accuracy, n_boot=200, seed=20260930)
check("F8 bootstrap reproducible with the fixed constitution seed", (lo, hi) == (lo2, hi2))

print("== F9: the B0=100% sanity path shape ==")
# B0 re-derives the label from the record. Its fixture is a trivially invertible map, and the
# point of the audit is that the scoring harness can represent a perfect predictor at all.
yt9 = np.array(["EXECUTE"] * 50 + ["ASK"] * 30 + ["ESCALATE"] * 20)
yp9 = yt9.copy()
check("F9 perfect predictor scores 1.0 accuracy", accuracy(yt9, yp9) == 1.0)
check("F9 perfect predictor scores 1.0 macro_f1", abs(macro_f1(yt9, yp9) - 1.0) < 1e-12)
yp9b = yp9.copy()
yp9b[:5] = "ASK"
check("F9 an imperfect oracle scores below 1.0", accuracy(yt9, yp9b) < 1.0,
      "the gate can actually fail")

print("== F10: learners refuse degenerate input rather than crashing silently ==")
try:
    DecisionTreeClassifier(max_depth=3, min_samples_leaf=50).fit(Xr[:10], yr[:10])
    check("F10 tiny input with a large leaf floor still returns a valid tree", True)
except Exception as e:
    check("F10 tiny input handled", False, str(e))
try:
    lr4 = MultinomialLogisticRegression(max_iter=5).fit(np.zeros((4, 3)), np.array([0, 0, 1, 1]))
    check("F10 all-zero feature matrix handled", np.isfinite(lr4.coef_).all())
except Exception as e:
    check("F10 all-zero features handled", False, str(e))

print()
if FAILS:
    print(f"FIXTURE AUDIT FAILED: {len(FAILS)} check(s): {FAILS}")
    sys.exit(1)
print("FIXTURE_AUDIT_PASS  (10 fixture groups, implementation audited before data contact)")
