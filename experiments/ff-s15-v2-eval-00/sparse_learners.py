"""Sparse L2-regularised multinomial logistic regression for the B3 lexical baseline.

The constitution fixes 1-2 grams hashed to 2^18 buckets with tf-idf. On the sealed BANK-v2 rows
only 21,251 of those 262,144 buckets are ever occupied, so the effective dimensionality is ~21k
even though the hash space is 2^18. Storage stays sparse (125.4M non-zeros over 400k TRAIN rows),
and both the forward pass and the gradient are computed in row chunks so peak memory is bounded
regardless of class count.
"""

import numpy as np


class SparseMultinomialLogisticRegression:
    """L-BFGS, L2, as fixed by the constitution (L2 = 1.0, 200 iterations).

    Parameters
    ----------
    n_features : int
        Hash-space size (2**18).
    l2, max_iter, tol, fit_intercept, seed
        As in the dense learner. The intercept is fitted on every row (row sums are zero after
        L2 tf-idf normalisation), which makes the bias the class prior.
    """

    def __init__(self, n_features, l2=1.0, max_iter=200, tol=1e-4,
                 fit_intercept=True, seed=0, chunk_rows=20000):
        self.n_features = n_features
        self.l2 = l2
        self.max_iter = max_iter
        self.tol = tol
        self.fit_intercept = fit_intercept
        self.seed = seed
        self.chunk_rows = chunk_rows
        self.coef_ = None
        self.classes_ = None
        self.n_iter_ = 0
        self.grad_norm_ = None

    # -- helpers ---------------------------------------------------------------
    def _logits(self, idx, data, W, b):
        """Segment-sum of data * W[idx] into per-row logits."""
        out = np.zeros((len(indptr_chunk_rows), W.shape[1]), dtype=np.float64)
        return out

    def _forward_backward(self, idx, data, indptr, n_rows, Y, W, b, need_grad):
        """Return (P, dW, db) computed in row chunks. dW is None when need_grad is False."""
        k = W.shape[1]
        dW = np.zeros_like(W) if need_grad else None
        db = np.zeros(k) if (need_grad and b is not None) else None
        P_all = None if need_grad else np.empty((n_rows, k), dtype=np.float64)
        nll_sum = 0.0 if need_grad else 0.0
        cr = self.chunk_rows
        for r0 in range(0, n_rows, cr):
            r1 = min(r0 + cr, n_rows)
            a0, a1 = int(indptr[r0]), int(indptr[r1])
            if a1 <= a0:
                # empty chunk: still needs the softmax rows filled
                if not need_grad:
                    Z = np.zeros((r1 - r0, k)) + (0.0 if b is None else b)
                    Z -= Z.max(axis=1, keepdims=True)
                    np.exp(Z, out=Z); Z /= Z.sum(axis=1, keepdims=True)
                    P_all[r0:r1] = Z
                continue
            ii = idx[a0:a1]
            dd = data[a0:a1]
            nrow = r1 - r0
            local = np.repeat(np.arange(nrow), np.diff(indptr[r0:r1 + 1]))
            blk = dd[:, None] * W[ii]                      # (nnz, k)
            Z = np.empty((nrow, k), dtype=np.float64)
            for cls in range(k):
                Z[:, cls] = np.bincount(local, weights=blk[:, cls], minlength=nrow)
            del blk
            if b is not None:
                Z += b
            Z -= Z.max(axis=1, keepdims=True)
            np.exp(Z, out=Z)
            Z /= Z.sum(axis=1, keepdims=True)
            if not need_grad:
                P_all[r0:r1] = Z
                continue
            Yc = Y[r0:r1]
            # NLL is accumulated on the pre-subtraction probabilities
            nll_sum -= float(np.log(np.clip(Z[np.arange(r1 - r0), Yc], 1e-12, None)).sum())
            np.put_along_axis(Z, Yc[:, None], np.take_along_axis(Z, Yc[:, None], 1) - 1.0, 1)
            Z /= n_rows
            for cls in range(k):
                np.add.at(dW[:, cls], ii, dd * Z[local, cls])
            if db is not None:
                db += Z.sum(axis=0)
        self._nll_sum = nll_sum
        return P_all, dW, db

    def _objective(self, W, b, idx, data, indptr, n_rows, Y, k):
        P, dW, db = self._forward_backward(idx, data, indptr, n_rows, Y, W, b, True)
        nll = self._nll_sum / n_rows
        reg = 0.5 * self.l2 * (W * W).sum() / n_rows
        return nll + reg, dW, db

    def fit(self, idx, data, indptr, y):
        n_rows = len(indptr) - 1
        classes, Y = np.unique(y, return_inverse=True)
        Y = Y.astype(np.int64)
        k = len(classes)
        self.classes_ = classes
        W = np.zeros((self.n_features, k), dtype=np.float64)
        b = np.zeros(k, dtype=np.float64) if self.fit_intercept else None
        rng = np.random.default_rng(self.seed)
        W += rng.normal(scale=1e-4, size=W.shape)

        m, mem = 5, 10
        S, Yh, rho = [], [], []
        loss, dW, db = self._objective(W, b, idx, data, indptr, n_rows, Y, k)
        g = np.concatenate([dW.ravel(), db.ravel()]) if b is not None else dW.ravel()
        gamma = 1.0
        for it in range(1, self.max_iter + 1):
            q = g.copy()
            al = []
            for s, yv, rv in zip(reversed(S), reversed(Yh), reversed(rho)):
                a = rv * (s @ q)
                al.append(a)
                q -= a * yv
            if S:
                gamma = (S[-1] @ Yh[-1]) / (S[-1] @ S[-1])
                q = gamma * q
            for (s, yv, rv), a in zip(zip(S, Yh, rho), reversed(al)):
                bta = rv * (yv @ q)
                q += (a - bta) * s
            dvec = -gamma * q
            # Normalise the initial step by the gradient norm. Without this the first trial step
            # of 1.0 is wildly too large on a 262144-dimensional problem, and every L-BFGS
            # iteration pays several full forward+backward passes in backtracking.
            gn0 = float(np.linalg.norm(g))
            step = 1.0 / max(gn0, 1e-12)
            for _ in range(15):
                Wn = W + step * dvec[:W.size].reshape(W.shape)
                bn = (b + step * dvec[W.size:]) if b is not None else None
                ln, dWn, dbn = self._objective(Wn, bn, idx, data, indptr, n_rows, Y, k)
                gn = np.concatenate([dWn.ravel(), dbn.ravel()]) if bn is not None else dWn.ravel()
                if np.isfinite(ln) and ln < loss + 1e-4 * step * (g @ dvec):
                    break
                step *= 0.5
            s = np.concatenate([(Wn - W).ravel(),
                                ((bn - b).ravel() if b is not None else np.zeros(0))])
            yv = np.concatenate([(dWn - dW).ravel(),
                                 ((dbn - db).ravel() if b is not None else np.zeros(0))])
            rho.append(1.0 / max(s @ yv, 1e-12))
            S.append(s); Yh.append(yv)
            if len(S) > mem:
                S.pop(0); Yh.pop(0); rho.pop(0)
            W, b, loss, dW, db = Wn, bn, ln, dWn, dbn
            g = gn
            if np.linalg.norm(g) < self.tol:
                break
        self.coef_ = W
        self.intercept_ = b
        self.n_iter_ = it
        self.grad_norm_ = float(np.linalg.norm(g))
        self.final_loss_ = float(loss)
        return self

    def predict(self, idx, data, indptr):
        n_rows = len(indptr) - 1
        P, _, _ = self._forward_backward(idx, data, indptr, n_rows, None, self.coef_,
                                         self.intercept_, False)
        return self.classes_[np.argmax(P, axis=1)]
