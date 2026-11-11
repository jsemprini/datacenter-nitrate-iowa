"""Shared estimators: two-way fixed-effect imputation, FWL event study, randomization inference.

All functions are deterministic given their inputs (randomization uses an explicit seed).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

EARTH_R_KM = 6371.0088


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * EARTH_R_KM * np.arcsin(np.sqrt(h))


# ----------------------------------------------------------------------------- two-way FE

def twoway_fit(y: np.ndarray, u: np.ndarray, t: np.ndarray, tol: float = 1e-12, max_iter: int = 10_000):
    """Least-squares unit and time effects (y ~ a_u + b_t) by alternating projections.

    u and t are integer codes. Returns (a, b) arrays indexed by code. Unbalanced panels are fine.
    """
    nu, nt = u.max() + 1, t.max() + 1
    cu = np.bincount(u, minlength=nu).astype(float)
    ct = np.bincount(t, minlength=nt).astype(float)
    a = np.zeros(nu)
    b = np.zeros(nt)
    for _ in range(max_iter):
        a_new = np.bincount(u, weights=y - b[t], minlength=nu) / np.where(cu > 0, cu, 1)
        b_new = np.bincount(t, weights=y - a_new[u], minlength=nt) / np.where(ct > 0, ct, 1)
        delta = max(np.abs(a_new - a).max(), np.abs(b_new - b).max())
        a, b = a_new, b_new
        if delta < tol:
            break
    return a, b


def demean_twoway(M: np.ndarray, u: np.ndarray, t: np.ndarray, tol: float = 1e-12, max_iter: int = 10_000):
    """Residualise each column of M on unit and time dummies (FWL)."""
    M = np.atleast_2d(M.T).T.astype(float)
    out = np.empty_like(M)
    for j in range(M.shape[1]):
        a, b = twoway_fit(M[:, j], u, t, tol, max_iter)
        out[:, j] = M[:, j] - a[u] - b[t]
    return out


def codes(*cols) -> np.ndarray:
    key = pd.Series(list(zip(*cols))) if len(cols) > 1 else pd.Series(cols[0])
    return pd.factorize(key)[0]


# ----------------------------------------------------------------------------- stacking

def build_stack(panel: pd.DataFrame, events: list[dict], controls: set, outcome: str,
                window: tuple[int, int] = (-7, 7), time_fe: str = "year") -> pd.DataFrame:
    """Stacked sub-experiments: each event keeps its treated units plus clean controls.

    events: dicts with keys id, g (first construction year), treated (set of pwsid).
    Units treated in one event never serve as controls in any event.
    """
    all_treated = set().union(*[e["treated"] for e in events]) if events else set()
    ctrl = sorted(set(controls) - all_treated)
    parts = []
    for e in events:
        if not e["treated"]:
            continue
        sub = panel.loc[panel.pwsid.isin(set(e["treated"]) | set(ctrl))].copy()
        sub["event"] = e["id"]
        sub["g"] = e["g"]
        sub["k"] = sub.year - e["g"]
        sub = sub.loc[sub.k.between(*window)]
        sub["treated_unit"] = sub.pwsid.isin(e["treated"]).astype(int)
        sub["D"] = ((sub.treated_unit == 1) & (sub.k >= 0)).astype(int)
        parts.append(sub)
    if not parts:
        return pd.DataFrame()
    s = pd.concat(parts, ignore_index=True)
    s = s.dropna(subset=[outcome])
    s["u"] = codes(s.event, s.pwsid)
    s["t"] = codes(s.event, s[time_fe])
    return s


def imputation_att(stack: pd.DataFrame, outcome: str, shift: float = 0.0) -> dict:
    """Borusyak-Jaravel-Spiess imputation estimator on a stacked panel.

    Fits unit and event-specific time effects on untreated observations only and
    averages (Y - Y0_hat) over treated post observations. `shift` subtracts a
    hypothesised constant effect from treated observations (for test inversion).
    """
    if stack.empty or stack.D.sum() == 0:
        return {"att": np.nan, "n_treated_obs": 0}
    y = stack[outcome].to_numpy(float) - shift * stack.D.to_numpy()
    d = stack.D.to_numpy().astype(bool)
    u, t = stack.u.to_numpy(), stack.t.to_numpy()
    a, b = twoway_fit(y[~d], u[~d], t[~d])
    seen_u = np.bincount(u[~d], minlength=u.max() + 1) > 0
    seen_t = np.bincount(t[~d], minlength=t.max() + 1) > 0
    ok = d & seen_u[u] & seen_t[t]
    if not ok.any():
        return {"att": np.nan, "n_treated_obs": 0}
    tau = y[ok] - a[u[ok]] - b[t[ok]]
    return {"att": float(tau.mean()), "n_treated_obs": int(ok.sum()),
            "n_treated_units": int(stack.loc[ok, ["event", "pwsid"]].drop_duplicates().shape[0]),
            "dropped_treated_obs": int((d & ~ok).sum()), "tau_obs": tau,
            "k_obs": stack.k.to_numpy()[ok]}


def event_study(stack: pd.DataFrame, outcome: str, kmin: int = -6, kmax: int = 6, ref: int = -1,
                cluster: str | None = None) -> pd.DataFrame:
    """Dynamic stacked regression via FWL: event-specific unit/time FE + relative-time dummies.

    Endpoints are binned. SEs are cluster-robust (CR1) on `cluster` for descriptive comparison
    only; design-based inference is done separately by randomization inference.
    """
    s = stack.copy()
    kk = s.k.clip(kmin, kmax)
    names, cols = [], []
    for k in range(kmin, kmax + 1):
        if k == ref:
            continue
        cols.append(((s.treated_unit == 1) & (kk == k)).astype(float).to_numpy())
        names.append(k)
    X = np.column_stack(cols)
    keep = X.sum(axis=0) > 0
    X, names = X[:, keep], [n for n, kp in zip(names, keep) if kp]
    u, t = s.u.to_numpy(), s.t.to_numpy()
    yt = demean_twoway(s[outcome].to_numpy(float)[:, None], u, t)[:, 0]
    Xt = demean_twoway(X, u, t)
    beta, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
    res = yt - Xt @ beta
    se = np.full(len(beta), np.nan)
    if cluster is not None:
        g = pd.factorize(s[cluster])[0]
        G = g.max() + 1
        XtX_inv = np.linalg.pinv(Xt.T @ Xt)
        meat = np.zeros((len(beta), len(beta)))
        for j in range(G):
            sc = Xt[g == j].T @ res[g == j]
            meat += np.outer(sc, sc)
        n, k = len(yt), len(beta) + u.max() + 1 + t.max() + 1
        V = XtX_inv @ meat @ XtX_inv * (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
        se = np.sqrt(np.diag(V))
    return pd.DataFrame({"k": names, "beta": beta, "se_cluster": se})


def did_static(stack: pd.DataFrame, outcome: str, cluster: str) -> dict:
    """Static stacked TWFE DiD with CR1 cluster SE (shown for comparison with the original)."""
    u, t = stack.u.to_numpy(), stack.t.to_numpy()
    yt = demean_twoway(stack[outcome].to_numpy(float)[:, None], u, t)[:, 0]
    xt = demean_twoway(stack.D.to_numpy(float)[:, None], u, t)[:, 0]
    b = float((xt @ yt) / (xt @ xt))
    r = yt - b * xt
    g = pd.factorize(stack[cluster])[0]
    G = g.max() + 1
    meat = sum((xt[g == j] @ r[g == j]) ** 2 for j in range(G))
    n, k = len(yt), 1 + u.max() + 1 + t.max() + 1
    v = meat / (xt @ xt) ** 2 * (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1))
    se = float(np.sqrt(v))
    p = float(2 * stats.t.sf(abs(b / se), G - 1)) if se > 0 else np.nan
    return {"beta": b, "se": se, "p": p, "G": int(G), "n": int(n)}


def cr1_static(y, D, u, t, g):
    """Static TWFE DiD coefficient and CR1 p-value from arrays (used for the size check)."""
    yt = demean_twoway(np.asarray(y, float)[:, None], u, t)[:, 0]
    xt = demean_twoway(np.asarray(D, float)[:, None], u, t)[:, 0]
    sxx = xt @ xt
    if sxx < 1e-12:
        return np.nan, np.nan
    b = float(xt @ yt / sxx)
    r = yt - b * xt
    G = g.max() + 1
    meat = np.bincount(g, weights=xt * r, minlength=G)
    n, k = len(yt), 1 + u.max() + 1 + t.max() + 1
    v = float((meat ** 2).sum() / sxx ** 2 * (G / max(G - 1, 1)) * ((n - 1) / max(n - k, 1)))
    se = np.sqrt(v)
    return b, float(2 * stats.t.sf(abs(b / se), G - 1)) if se > 0 else np.nan


# ----------------------------------------------------------------------------- inference helpers

def tost(beta: float, se: float, df: float, delta: float) -> dict:
    p = max(stats.t.sf((beta + delta) / se, df), stats.t.cdf((beta - delta) / se, df))
    h = stats.t.ppf(0.95, df) * se
    return {"p_tost": float(p), "ci90": [float(beta - h), float(beta + h)], "equivalent": bool(p < 0.05)}


def ri_pvalue(obs: float, null_draws: np.ndarray) -> float:
    """Two-sided randomization p-value with the observed assignment counted (Phipson-Smyth)."""
    d = np.asarray(null_draws, dtype=float)
    d = d[np.isfinite(d)]
    return float((1 + np.sum(np.abs(d) >= abs(obs) - 1e-12)) / (1 + len(d)))
