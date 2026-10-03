"""V2-0 baseline learners.

Implemented directly in numpy because sklearn is not available in this environment and because
the constitution fixes exact learner semantics; owning the implementation makes those semantics
auditable.

These learners are validated against hand-built fixtures with known-exact answers in
tests/test_learners_fixtures.py BEFORE any contact with the frozen 400k/50k rows.
"""

import numpy as np

# ---------------------------------------------------------------- multinomial logistic regression


def _softmax(scores):
    m = scores.max(axis=1, keepdims=True)
    e = np.exp(scores - m)
    return e / e.sum(axis=1, keepdims=True)


class MultinomialLogisticRegression:
    """L2-regularised multinomial logistic regression, L-BFGS, as fixed by the constitution.

    Parameters
    ----------
    l2 : float
        L2 penalty. The constitution fixes 1.0.
    max_iter : int
        L-BFGS iterations. The constitution fixes 200.
    tol : float
        Gradient-norm stopping tolerance.
    fit_intercept : bool
        Whether to fit a bias term. The constitution does not mention a bias; the default here is
        True because a schema-count model is otherwise origin-dependent. Recorded in the receipt.
    """

    def __init__(self, l2=1.0, max_iter=200, tol=1e-5, fit_intercept=True, seed=0):
        self.l2 = l2
        self.max_iter = max_iter
        self.tol = tol
        self.fit_intercept = fit_intercept
        self.seed = seed
        self.coef_ = None
        self.classes_ = None
        self.n_iter_ = 0
        self.grad_norm_ = None

    # -- objective ---------------------------------------------------------------
    def _objective(self, W, b, X, Y, n, k, d):
        Z = X @ W
        if b is not None:
            Z = Z + b
        P = _softmax(Z)
        # mean negative log-likelihood
        nll = -np.log(np.clip(P[np.arange(n), Y], 1e-12, None)).mean()
        # L2 on weights only, never on the intercept
        reg = 0.5 * self.l2 * (W * W).sum() / n
        loss = nll + reg
        dP = P.copy()
        dP[np.arange(n), Y] -= 1.0
        dP /= n
        gW = X.T @ dP + self.l2 * W / n
        gb = dP.sum(axis=0) if b is not None else None
        return loss, gW, gb

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y)
        classes, y_idx = np.unique(y, return_inverse=True)
        n, d = X.shape
        k = len(classes)
        self.classes_ = classes
        W = np.zeros((d, k), dtype=np.float64)
        b = np.zeros(k, dtype=np.float64) if self.fit_intercept else None

        # L-BFGS (two-loop recursion) with a simple backtracking line search.
        m, mem = 5, 10
        S, Y_hist, rho = [], [], []
        rng = np.random.default_rng(self.seed)
        # deterministic, tiny jitter breaks the symmetry of the zero start
        W += rng.normal(scale=1e-4, size=W.shape)
        loss, gW, gb = self._objective(W, b, X, y_idx, n, k, d)
        g = np.concatenate([gW.ravel(), gb.ravel()]) if b is not None else gW.ravel()
        it = 0
        for it in range(1, self.max_iter + 1):
            q = g.copy()
            al = []
            for s, yv, rv in zip(reversed(S), reversed(Y_hist), reversed(rho)):
                a = rv * (s @ q)
                al.append(a)
                q -= a * yv
            if S:
                s_last, y_last = S[-1], Y_hist[-1]
                gamma = (s_last @ y_last) / (s_last @ s_last)
                q = gamma * q
            for (s, yv, rv), a in zip(zip(S, Y_hist, rho), reversed(al)):
                bta = rv * (yv @ q)
                q += (a - bta) * s
            if S:
                s_last, y_last = S[-1], Y_hist[-1]
                gamma = (s_last @ y_last) / (s_last @ s_last)
                dvec = -gamma * q
            else:
                dvec = -q
            # backtracking line search
            step = 1.0
            for _ in range(20):
                Wn = W + step * dvec[:d * k].reshape(d, k)
                bn = (b + step * dvec[d * k:]) if b is not None else None
                ln, gWn, gbn = self._objective(Wn, bn, X, y_idx, n, k, d)
                gn = np.concatenate([gWn.ravel(), gbn.ravel()]) if bn is not None else gWn.ravel()
                if np.isfinite(ln) and ln < loss + 1e-4 * step * (g @ dvec):
                    break
                step *= 0.5
            s = np.concatenate([(Wn - W).ravel(), ((bn - b).ravel() if b is not None else np.zeros(0))])
            yv = np.concatenate([(gWn - gW).ravel(), ((gbn - gb).ravel() if b is not None else np.zeros(0))])
            rho.append(1.0 / max(s @ yv, 1e-12))
            S.append(s)
            Y_hist.append(yv)
            if len(S) > mem:
                S.pop(0)
                Y_hist.pop(0)
                rho.pop(0)
            W, b, loss, gW, gb = Wn, bn, ln, gWn, gbn
            g = gn
            if np.linalg.norm(g) < self.tol:
                break
        self.coef_ = W
        self.intercept_ = b
        self.n_iter_ = it
        self.grad_norm_ = float(np.linalg.norm(g))
        self.final_loss_ = float(loss)
        return self

    def decision_function(self, X):
        X = np.asarray(X, dtype=np.float64)
        Z = X @ self.coef_
        if self.intercept_ is not None:
            Z = Z + self.intercept_
        return Z

    def predict(self, X):
        return self.classes_[np.argmax(self.decision_function(X), axis=1)]


# ---------------------------------------------------------------- decision tree (CART)


class DecisionTreeClassifier:
    """CART decision tree, gini split, as fixed by the constitution.

    Parameters
    ----------
    max_depth : int
        Maximum depth. Constitution fixes 6 (B4) and 8 (B5).
    min_samples_leaf : int
        Constitution fixes 50 for both B4 and B5.
    """

    def __init__(self, max_depth=6, min_samples_leaf=50, seed=0):
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.seed = seed
        self.tree_ = None
        self.classes_ = None

    def fit(self, X, y):
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y)
        self.classes_, y_idx = np.unique(y, return_inverse=True)
        k = len(self.classes_)
        rng = np.random.default_rng(self.seed)
        # deterministic feature-order tiebreak
        self.order_ = rng.permutation(X.shape[1])
        counts = np.bincount(y_idx, minlength=k).astype(np.float64)
        self.tree_ = self._build(X, y_idx, 0, counts)
        return self

    def _gini(self, counts):
        tot = counts.sum()
        if tot <= 0:
            return 0.0
        p = counts / tot
        return 1.0 - (p * p).sum()

    def _build(self, X, y, depth, counts):
        k = len(self.classes_)
        node = {"depth": depth, "n": int(y.size), "counts": counts.copy()}
        node["impurity"] = self._gini(counts)
        if depth >= self.max_depth or node["impurity"] <= 0.0 or y.size < 2 * self.min_samples_leaf:
            node["leaf"] = True
            node["prediction"] = self.classes_[int(np.argmax(counts))]
            return node
        best = None
        parent = node["impurity"]
        for j in self.order_:
            col = X[:, j]
            uniq = np.unique(col)
            if uniq.size < 2:
                continue
            # candidate thresholds at midpoints between consecutive distinct values
            thr = (uniq[:-1] + uniq[1:]) / 2.0
            for t in thr:
                left = col <= t
                nl = int(left.sum())
                nr = y.size - nl
                if nl < self.min_samples_leaf or nr < self.min_samples_leaf:
                    continue
                cl = np.bincount(y[left], minlength=k).astype(np.float64)
                cr = np.bincount(y[~left], minlength=k).astype(np.float64)
                w = (nl * self._gini(cl) + nr * self._gini(cr)) / y.size
                if best is None or w < best[0] - 1e-12:
                    best = (w, j, t, left, cl, cr)
        if best is None or best[0] >= parent - 1e-12:
            node["leaf"] = True
            node["prediction"] = self.classes_[int(np.argmax(counts))]
            return node
        _, j, t, left, cl, cr = best
        node["leaf"] = False
        node["feature"] = int(j)
        node["threshold"] = float(t)
        node["left"] = self._build(X[left], y[left], depth + 1, cl)
        node["right"] = self._build(X[~left], y[~left], depth + 1, cr)
        return node

    def predict_one(self, x, node=None):
        node = self.tree_ if node is None else node
        if node["leaf"]:
            return node["prediction"]
        return self.predict_one(x, node["left"] if x[node["feature"]] <= node["threshold"] else node["right"])

    def predict(self, X):
        X = np.asarray(X, dtype=np.float64)
        return np.array([self.predict_one(x) for x in X])

    def max_depth_reached(self):
        def depth_of(n):
            return 0 if n["leaf"] else 1 + max(depth_of(n["left"]), depth_of(n["right"]))
        return depth_of(self.tree_)

    def top_features(self, n=10):
        """Split-importance ranking, used by decision rule 3 (name the cue-bearing features)."""
        counts = {}

        def walk(node):
            if node["leaf"]:
                return
            counts[node["feature"]] = counts.get(node["feature"], 0) + 1
            walk(node["left"])
            walk(node["right"])

        walk(self.tree_)
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:n]


# ---------------------------------------------------------------- metrics


def macro_f1(y_true, y_pred, classes=None):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    if classes is None:
        classes = np.unique(np.concatenate([y_true, y_pred]))
    f1s = []
    for c in classes:
        tp = int(((y_pred == c) & (y_true == c)).sum())
        fp = int(((y_pred == c) & (y_true != c)).sum())
        fn = int(((y_pred != c) & (y_true == c)).sum())
        if tp == 0 and (fp > 0 or fn > 0):
            f1s.append(0.0)
        elif tp == 0 and fp == 0 and fn == 0:
            continue  # class absent from both truth and prediction: not scored
        else:
            f1s.append(2 * tp / (2 * tp + fp + fn))
    return float(np.mean(f1s)) if f1s else 0.0


def accuracy(y_true, y_pred):
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    if y_true.size == 0:
        return 0.0
    return float((y_true == y_pred).mean())


def percentile_bootstrap_ci(y_true, y_pred, stat_fn, n_boot=1000, seed=20260930, alpha=0.05):
    """Percentile bootstrap over rows, fixed seed, as fixed by the constitution."""
    y_true = np.asarray(y_true)
    y_pred = np.asarray(y_pred)
    rng = np.random.default_rng(seed)
    n = y_true.size
    vals = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, size=n)
        vals.append(stat_fn(y_true[idx], y_pred[idx]))
    vals = np.sort(np.array(vals))
    lo = float(np.quantile(vals, alpha / 2))
    hi = float(np.quantile(vals, 1 - alpha / 2))
    return lo, hi
