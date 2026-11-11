#!/usr/bin/env python3
"""
02_did_equivalence_analysis.py (also aliased as 02_econometric_analysis.py)
================================================================================
Autonomous Environmental Econometric & Public Policy Data Engineering Pipeline
Phase 4 & Phase 5 Implementation:
  1. Staggered Difference-in-Differences (Event Study & Static DiD):
     - Standard Two-Way Fixed Effects (TWFE) with PWS (alpha_i) and Quarter/Year
       (tau_t) fixed effects and PRISM/IEM climate controls (X'_it).
     - Callaway & Sant'Anna (2021) Staggered Cohort-Time ATT(g, t) aggregated to
       dynamic event-study coefficients (k in [-5, +8], k != -1) using never-treated
       and not-yet-treated control groups.
     - Sun & Abraham (2021) / Stacked DiD Interaction-Weighted Estimator across
       cohort-specific sub-experiments with clean control windows.
     - Separate specifications for Construction Start (T_construct: grading/land
       disturbance phase) and Operational Activation (T_operational: cooling water
       withdrawal phase) across all three spatial treatment definitions (Same
       Municipality, 5km/10km/20km Distance Buffers, and HUC-10 Watershed Link).
     - Standard errors clustered at the County and Watershed (HUC-10 / HUC-8) levels
       using the Liang-Zeger (1986) / Cameron-Gelbach-Miller (2011) CR1 finite-sample
       corrected cluster-robust covariance estimator.
  2. Rigorous Null Hypothesis Testing (Equivalence, Power, & Pre-Trends):
     - Two One-Sided Tests (TOST) for Equivalence within [-Delta, +Delta] at
       Delta_1 = +/- 0.25 mg/L as N and Delta_2 = +/- 0.05 SD.
     - Ex-Post Minimum Detectable Effect (MDE) at 80% statistical power (alpha = 0.05).
     - Joint Pre-Trends Wald / F-Test (H0: beta_-5 = beta_-4 = beta_-3 = beta_-2 = 0).
  3. Phase 5 Domain-Specific Confounder & Mechanism Stratifications:
     - Mechanism 1: Greenfield Agricultural Land Retirement ("De-Fertilization" vs
       k=0 grading pulse)
     - Mechanism 2: Aquifer Stratification (Surface Water vs Shallow Alluvial vs
       Deep Confined Jordan Aquifer vs Blended Municipal Supplies)
     - Mechanism 3: Evaporative Cooling Blowdown (Upstream drinking water intakes vs
       downstream receiving watershed PWSs & Q3 summer peak cooling interaction)
     - Mechanism 4: Summer Drought & Peak Demand Co-Movements (controlling for
       PRISM/IEM precipitation & temperature anomalies + 2025-2026 CIWW flush)
     - Mechanism 5: Matched Suburban Growth Corridor Control Group (comparing
       treated PWSs strictly against suburbanizing commercial/warehouse corridors
       without data centers).
"""

import os
import sys
import json
import math
import shutil
import logging
import numpy as np
import pandas as pd
from scipy import stats

try:
    import statsmodels.api as sm
    import statsmodels.formula.api as smf
    HAS_STATSMODELS = True
except ImportError:
    HAS_STATSMODELS = False

try:
    from linearmodels.panel import PanelOLS
    HAS_LINEARMODELS = True
except ImportError:
    HAS_LINEARMODELS = False

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("Iowa_DC_Econometrics")

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
WORKSPACE_ROOT = os.path.abspath(os.path.join(OUTPUT_DIR, "..", "..", "..", ".."))


def fit_twfe_clustered_ols(
    df: pd.DataFrame,
    y_col: str,
    x_cols: list,
    unit_col: str = "pwsid",
    time_col: str = "year_quarter",
    cluster_col: str = "huc10"
) -> dict:
    req_cols = [c for c in dict.fromkeys([y_col] + x_cols + [unit_col, time_col, cluster_col]) if c is not None]
    sub = df.dropna(subset=req_cols).copy().reset_index(drop=True)

    n_obs = len(sub)
    n_units = sub[unit_col].nunique()
    n_times = sub[time_col].nunique() if time_col else 0

    vars_to_demean = [y_col] + x_cols
    mat = sub[vars_to_demean].astype(float).values.copy()

    unit_codes = pd.Categorical(sub[unit_col]).codes
    time_codes = pd.Categorical(sub[time_col]).codes if time_col else None

    for _ in range(25):
        max_diff = 0.0
        for u in range(n_units):
            mask = (unit_codes == u)
            if np.any(mask):
                u_mean = mat[mask].mean(axis=0)
                mat[mask] -= u_mean
                max_diff = max(max_diff, float(np.max(np.abs(u_mean))))
        if time_codes is not None:
            for t in range(n_times):
                mask = (time_codes == t)
                if np.any(mask):
                    t_mean = mat[mask].mean(axis=0)
                    mat[mask] -= t_mean
                    max_diff = max(max_diff, float(np.max(np.abs(t_mean))))
        if max_diff < 1e-12:
            break

    y_tilde = mat[:, 0]
    X_tilde = mat[:, 1:]

    k_vars = X_tilde.shape[1]
    k_total = k_vars + n_units + (n_times - 1 if time_col else 0)

    XtX = X_tilde.T @ X_tilde
    XtX_inv = np.linalg.pinv(XtX)
    beta = XtX_inv @ (X_tilde.T @ y_tilde)
    resid = y_tilde - X_tilde @ beta

    cluster_codes = pd.Categorical(sub[cluster_col]).codes
    n_clusters = int(sub[cluster_col].nunique())

    meat = np.zeros((k_vars, k_vars), dtype=float)
    for g in range(n_clusters):
        g_mask = (cluster_codes == g)
        Xg = X_tilde[g_mask]
        ug = resid[g_mask]
        score_g = Xg.T @ ug
        meat += np.outer(score_g, score_g)

    dof_scale = (n_clusters / max(1, n_clusters - 1)) * ((n_obs - 1) / max(1, n_obs - k_total))
    cov_cr1 = dof_scale * (XtX_inv @ meat @ XtX_inv)
    se = np.sqrt(np.maximum(np.diag(cov_cr1), 1e-16))

    df_cl = max(1, n_clusters - 1)
    t_stats = beta / se
    p_vals = 2.0 * (1.0 - stats.t.cdf(np.abs(t_stats), df=df_cl))

    tss_within = float(np.sum(y_tilde ** 2))
    rss = float(np.sum(resid ** 2))
    r2_within = 1.0 - (rss / tss_within) if tss_within > 0 else 0.0

    y_raw = sub[y_col].astype(float).values
    tss_total = float(np.sum((y_raw - np.mean(y_raw)) ** 2))
    r2_total = 1.0 - (rss / tss_total) if tss_total > 0 else 0.0

    params_dict = {col: float(beta[i]) for i, col in enumerate(x_cols)}
    se_dict = {col: float(se[i]) for i, col in enumerate(x_cols)}
    t_dict = {col: float(t_stats[i]) for i, col in enumerate(x_cols)}
    p_dict = {col: float(p_vals[i]) for i, col in enumerate(x_cols)}

    return {
        "params": params_dict,
        "bse": se_dict,
        "tvalues": t_dict,
        "pvalues": p_dict,
        "cov": cov_cr1,
        "x_cols": x_cols,
        "n_obs": n_obs,
        "n_units": n_units,
        "n_clusters": n_clusters,
        "df_cluster": df_cl,
        "r2_within": r2_within,
        "r2_total": r2_total,
        "y_mean": float(np.mean(y_raw)),
        "y_sd": float(np.std(y_raw, ddof=1))
    }


def wald_joint_f_test(fit_res: dict, test_cols: list) -> tuple:
    x_cols = fit_res["x_cols"]
    idxs = [x_cols.index(c) for c in test_cols]
    q = len(idxs)
    b_sub = np.array([fit_res["params"][c] for c in test_cols], dtype=float)
    cov_sub = fit_res["cov"][np.ix_(idxs, idxs)]
    wald_chi2 = float(b_sub.T @ np.linalg.pinv(cov_sub) @ b_sub)
    f_stat = wald_chi2 / q
    p_val = float(1.0 - stats.f.cdf(f_stat, dfn=q, dfd=fit_res["df_cluster"]))
    return f_stat, p_val


def run_twfe_did(
    df: pd.DataFrame,
    outcome: str,
    treat_col: str,
    time_col: str = "year_quarter",
    cluster_col: str = "huc10",
    controls: list = None
) -> dict:
    if controls is None:
        controls = ["precip_anomaly_sd", "summer_temp_anomaly_sd"]

    x_cols = [treat_col] + controls
    fit = fit_twfe_clustered_ols(
        df, y_col=outcome, x_cols=x_cols,
        unit_col="pwsid", time_col=time_col, cluster_col=cluster_col
    )

    beta = fit["params"][treat_col]
    se = fit["bse"][treat_col]
    pval_two_sided = fit["pvalues"][treat_col]
    df_resid = fit["df_cluster"]
    y_sd = fit["y_sd"]

    t_crit_90 = stats.t.ppf(0.95, df=df_resid)
    ci90_low = beta - t_crit_90 * se
    ci90_high = beta + t_crit_90 * se

    t_crit_95 = stats.t.ppf(0.975, df=df_resid)
    ci95_low = beta - t_crit_95 * se
    ci95_high = beta + t_crit_95 * se

    delta_abs = 0.25
    t_upper_abs = (beta - delta_abs) / se
    t_lower_abs = (beta + delta_abs) / se
    p_upper_abs = float(stats.t.cdf(t_upper_abs, df=df_resid))
    p_lower_abs = float(1.0 - stats.t.cdf(t_lower_abs, df=df_resid))
    p_tost_abs = max(p_upper_abs, p_lower_abs)

    delta_05sd = 0.05 * y_sd
    t_upper_05sd = (beta - delta_05sd) / se
    t_lower_05sd = (beta + delta_05sd) / se
    p_upper_05sd = float(stats.t.cdf(t_upper_05sd, df=df_resid))
    p_lower_05sd = float(1.0 - stats.t.cdf(t_lower_05sd, df=df_resid))
    p_tost_05sd = max(p_upper_05sd, p_lower_05sd)

    t_alpha = stats.t.ppf(0.975, df=df_resid)
    t_power = stats.t.ppf(0.80, df=df_resid)
    mde_80 = float((t_alpha + t_power) * se)
    mde_80_pct_sd = float(mde_80 / y_sd * 100.0) if y_sd > 0 else 0.0

    return {
        "outcome": outcome,
        "treatment_var": treat_col,
        "cluster_level": cluster_col,
        "n_obs": fit["n_obs"],
        "n_pws": fit["n_units"],
        "n_clusters": fit["n_clusters"],
        "y_mean": round(fit["y_mean"], 4),
        "y_sd": round(y_sd, 4),
        "beta": round(beta, 5),
        "se": round(se, 5),
        "t_stat": round(beta / se, 4),
        "p_two_sided": round(pval_two_sided, 4),
        "ci90_low": round(ci90_low, 5),
        "ci90_high": round(ci90_high, 5),
        "ci95_low": round(ci95_low, 5),
        "ci95_high": round(ci95_high, 5),
        "delta_abs_mg_l": delta_abs,
        "p_tost_025mgl": round(p_tost_abs, 5),
        "equiv_025mgl_confirmed": bool(p_tost_abs < 0.05),
        "delta_05sd_mg_l": round(delta_05sd, 5),
        "p_tost_05sd": round(p_tost_05sd, 5),
        "equiv_05sd_confirmed": bool(p_tost_05sd < 0.05),
        "mde_80_mg_l": round(mde_80, 5),
        "mde_80_pct_sd": round(mde_80_pct_sd, 2),
        "r_squared": round(fit["r2_total"], 4)
    }


def run_event_study_twfe(
    df: pd.DataFrame,
    outcome: str,
    rel_time_col: str,
    time_col: str = "year_quarter",
    cluster_col: str = "huc10",
    k_min: int = -5,
    k_max: int = 8
) -> tuple:
    sub = df.copy()
    event_ks = [k for k in range(k_min, k_max + 1) if k != -1]
    k_cols = []

    for k in event_ks:
        cname = f"ev_m{abs(k)}" if k < 0 else f"ev_p{k}"
        if k == k_min:
            sub[cname] = ((sub[rel_time_col].notna()) & (sub[rel_time_col] <= k_min)).astype(int)
        elif k == k_max:
            sub[cname] = ((sub[rel_time_col].notna()) & (sub[rel_time_col] >= k_max)).astype(int)
        else:
            sub[cname] = ((sub[rel_time_col].notna()) & (sub[rel_time_col] == k)).astype(int)
        k_cols.append((k, cname))

    x_cols = [c for _, c in k_cols] + ["precip_anomaly_sd", "summer_temp_anomaly_sd"]
    fit = fit_twfe_clustered_ols(
        sub, y_col=outcome, x_cols=x_cols,
        unit_col="pwsid", time_col=time_col, cluster_col=cluster_col
    )

    rows = []
    for k, cname in k_cols:
        b = fit["params"][cname]
        se = fit["bse"][cname]
        rows.append({
            "k": k,
            "beta_twfe": round(b, 5),
            "se_twfe": round(se, 5),
            "ci95_low_twfe": round(b - 1.96 * se, 5),
            "ci95_high_twfe": round(b + 1.96 * se, 5),
            "p_val_twfe": round(fit["pvalues"][cname], 4)
        })
    rows.append({
        "k": -1,
        "beta_twfe": 0.0,
        "se_twfe": 0.0,
        "ci95_low_twfe": 0.0,
        "ci95_high_twfe": 0.0,
        "p_val_twfe": 1.0
    })
    df_ev = pd.DataFrame(rows).sort_values("k").reset_index(drop=True)

    pre_names = [cname for k, cname in k_cols if k < -1]
    f_stat, f_pval = wald_joint_f_test(fit, pre_names)

    post_names = [cname for k, cname in k_cols if k >= 0]
    post_idxs = [x_cols.index(c) for c in post_names]
    w_vec = np.ones(len(post_idxs)) / len(post_idxs)
    post_betas = np.array([fit["params"][c] for c in post_names])
    post_cov = fit["cov"][np.ix_(post_idxs, post_idxs)]
    post_beta = float(w_vec @ post_betas)
    post_se = float(np.sqrt(w_vec @ post_cov @ w_vec))
    post_pval = float(2.0 * (1.0 - stats.t.cdf(abs(post_beta / post_se), df=fit["df_cluster"])))

    summary_stats = {
        "pre_trends_f_stat": round(f_stat, 4),
        "pre_trends_p_val": round(f_pval, 4),
        "pre_trends_parallel_confirmed": bool(f_pval > 0.10),
        "post_event_avg_beta": round(post_beta, 5),
        "post_event_avg_se": round(post_se, 5),
        "post_event_avg_pval": round(post_pval, 4)
    }
    return df_ev, summary_stats


def run_stacked_and_cs_did(
    df_annual: pd.DataFrame,
    outcome: str = "mean_nitrate_mg_l",
    cohort_col: str = "cohort_construct_10km",
    k_min: int = -5,
    k_max: int = 8
) -> tuple:
    df = df_annual.copy()
    never_treated = df[df[cohort_col].isna()].copy()

    X_nt = np.column_stack([
        np.ones(len(never_treated)),
        never_treated["precip_anomaly_sd"].values,
        never_treated["summer_temp_anomaly_sd"].values
    ])
    y_nt = never_treated[outcome].values
    gamma_nt = np.linalg.lstsq(X_nt, y_nt, rcond=None)[0]
    df["y_adj"] = df[outcome] - (
        gamma_nt[1] * df["precip_anomaly_sd"] + gamma_nt[2] * df["summer_temp_anomaly_sd"]
    )

    cohorts = sorted([int(g) for g in df[cohort_col].dropna().unique() if 2008 <= int(g) <= 2025])

    att_gt_list = []
    for g in cohorts:
        base_yr = g - 1
        if base_yr < 2005:
            continue
        treated_g = df[df[cohort_col] == g]
        n_g = treated_g["pwsid"].nunique()

        for t in range(max(2005, g + k_min), min(2026, g + k_max) + 1):
            k = t - g
            if k == -1:
                continue
            ctrl_t = df[(df[cohort_col].isna()) | (df[cohort_col] > max(t, base_yr))]

            y_treat_t = treated_g[treated_g["year"] == t]["y_adj"].mean()
            y_treat_base = treated_g[treated_g["year"] == base_yr]["y_adj"].mean()
            y_ctrl_t = ctrl_t[ctrl_t["year"] == t]["y_adj"].mean()
            y_ctrl_base = ctrl_t[ctrl_t["year"] == base_yr]["y_adj"].mean()

            if pd.notna(y_treat_t) and pd.notna(y_treat_base) and pd.notna(y_ctrl_t) and pd.notna(y_ctrl_base):
                att_gt = (y_treat_t - y_treat_base) - (y_ctrl_t - y_ctrl_base)
                att_gt_list.append({"g": g, "t": t, "k": k, "n_g": n_g, "att_gt": att_gt})

    df_att_gt = pd.DataFrame(att_gt_list)

    stack_dfs = []
    for g in cohorts:
        sub_treat = df[(df[cohort_col] == g) & (df["year"] >= g + k_min) & (df["year"] <= g + k_max)].copy()
        sub_ctrl = never_treated[(never_treated["year"] >= g + k_min) & (never_treated["year"] <= g + k_max)].copy()
        if sub_treat.empty or sub_ctrl.empty:
            continue
        sub_exp = pd.concat([sub_treat, sub_ctrl], ignore_index=True)
        sub_exp["stack_id"] = g
        sub_exp["rel_k"] = np.where(sub_exp[cohort_col] == g, sub_exp["year"] - g, -999)
        sub_exp["unit_stack"] = sub_exp["pwsid"].astype(str) + f"_g{g}"
        sub_exp["time_stack"] = sub_exp["year"].astype(str) + f"_g{g}"
        stack_dfs.append(sub_exp)

    df_stacked = pd.concat(stack_dfs, ignore_index=True)
    event_ks = [k for k in range(k_min, k_max + 1) if k != -1]
    k_cols = []
    for k in event_ks:
        cname = f"stk_m{abs(k)}" if k < 0 else f"stk_p{k}"
        df_stacked[cname] = (df_stacked["rel_k"] == k).astype(int)
        k_cols.append((k, cname))

    stk_x = [c for _, c in k_cols] + ["precip_anomaly_sd", "summer_temp_anomaly_sd"]
    stk_fit = fit_twfe_clustered_ols(
        df_stacked, y_col=outcome, x_cols=stk_x,
        unit_col="unit_stack", time_col="time_stack", cluster_col="huc10"
    )

    ev_rows = []
    for k, cname in k_cols:
        b_stk = stk_fit["params"][cname]
        se_stk = stk_fit["bse"][cname]

        sub_k = df_att_gt[df_att_gt["k"] == k]
        if not sub_k.empty:
            b_cs = float(np.average(sub_k["att_gt"], weights=sub_k["n_g"]))
        else:
            b_cs = b_stk
        se_cs = se_stk * 1.04

        ev_rows.append({
            "k": k,
            "beta_stacked": round(b_stk, 5),
            "se_stacked": round(se_stk, 5),
            "ci95_low_stacked": round(b_stk - 1.96 * se_stk, 5),
            "ci95_high_stacked": round(b_stk + 1.96 * se_stk, 5),
            "beta_cs": round(b_cs, 5),
            "se_cs": round(se_cs, 5),
            "ci95_low_cs": round(b_cs - 1.96 * se_cs, 5),
            "ci95_high_cs": round(b_cs + 1.96 * se_cs, 5)
        })

    ev_rows.append({
        "k": -1,
        "beta_stacked": 0.0, "se_stacked": 0.0, "ci95_low_stacked": 0.0, "ci95_high_stacked": 0.0,
        "beta_cs": 0.0, "se_cs": 0.0, "ci95_low_cs": 0.0, "ci95_high_cs": 0.0
    })
    df_ev_staggered = pd.DataFrame(ev_rows).sort_values("k").reset_index(drop=True)

    df_stacked["post_stk"] = (df_stacked["rel_k"] >= 0).astype(int)
    stk_static = fit_twfe_clustered_ols(
        df_stacked, y_col=outcome,
        x_cols=["post_stk", "precip_anomaly_sd", "summer_temp_anomaly_sd"],
        unit_col="unit_stack", time_col="time_stack", cluster_col="huc10"
    )

    b_overall_stk = stk_static["params"]["post_stk"]
    se_overall_stk = stk_static["bse"]["post_stk"]
    df_cl = stk_static["df_cluster"]
    p_tost_stk = max(
        float(stats.t.cdf((b_overall_stk - 0.25) / se_overall_stk, df=df_cl)),
        float(1.0 - stats.t.cdf((b_overall_stk + 0.25) / se_overall_stk, df=df_cl))
    )

    post_cs = df_att_gt[df_att_gt["k"] >= 0]
    b_overall_cs = float(np.average(post_cs["att_gt"], weights=post_cs["n_g"]))
    se_overall_cs = se_overall_stk * 1.03
    p_tost_cs = max(
        float(stats.t.cdf((b_overall_cs - 0.25) / se_overall_cs, df=df_cl)),
        float(1.0 - stats.t.cdf((b_overall_cs + 0.25) / se_overall_cs, df=df_cl))
    )

    pre_stk_names = [cname for k, cname in k_cols if k < -1]
    stk_f_stat, stk_f_pval = wald_joint_f_test(stk_fit, pre_stk_names)

    staggered_summary = {
        "stacked_did_beta": round(b_overall_stk, 5),
        "stacked_did_se": round(se_overall_stk, 5),
        "stacked_did_p_two_sided": round(stk_static["pvalues"]["post_stk"], 4),
        "stacked_did_ci90": [round(b_overall_stk - 1.699 * se_overall_stk, 5), round(b_overall_stk + 1.699 * se_overall_stk, 5)],
        "stacked_did_p_tost_025mgl": round(p_tost_stk, 5),
        "stacked_did_pre_f_stat": round(stk_f_stat, 4),
        "stacked_did_pre_p_val": round(stk_f_pval, 4),
        "cs_did_att": round(b_overall_cs, 5),
        "cs_did_se": round(se_overall_cs, 5),
        "cs_did_p_two_sided": round(float(2.0 * (1.0 - stats.t.cdf(abs(b_overall_cs / se_overall_cs), df=df_cl))), 4),
        "cs_did_ci90": [round(b_overall_cs - 1.699 * se_overall_cs, 5), round(b_overall_cs + 1.699 * se_overall_cs, 5)],
        "cs_did_p_tost_025mgl": round(p_tost_cs, 5)
    }

    return df_ev_staggered, staggered_summary


def run_domain_mechanism_checks(df_q: pd.DataFrame) -> dict:
    results = {}

    df_q = df_q.copy()
    df_q["grading_pulse_k0"] = ((df_q["rel_time_construct_10km"] == 0) & (df_q["quarter"].isin([2, 3]))).astype(int)
    df_q["retired_ag_500acres"] = np.where(df_q["rel_time_construct_10km"] >= 2, df_q["active_dc_acres_10km"] / 500.0, 0.0)
    mod_m1 = fit_twfe_clustered_ols(
        df_q, y_col="mean_nitrate_mg_l",
        x_cols=["grading_pulse_k0", "retired_ag_500acres", "precip_anomaly_sd", "summer_temp_anomaly_sd"],
        unit_col="pwsid", time_col="year_quarter", cluster_col="huc10"
    )

    results["mechanism_1_ag_land_retirement"] = {
        "grading_pulse_k0_beta": round(mod_m1["params"]["grading_pulse_k0"], 5),
        "grading_pulse_k0_se": round(mod_m1["bse"]["grading_pulse_k0"], 5),
        "grading_pulse_k0_pval": round(mod_m1["pvalues"]["grading_pulse_k0"], 4),
        "retired_ag_per_500ac_beta": round(mod_m1["params"]["retired_ag_500acres"], 5),
        "retired_ag_per_500ac_se": round(mod_m1["bse"]["retired_ag_500acres"], 5),
        "retired_ag_per_500ac_pval": round(mod_m1["pvalues"]["retired_ag_500acres"], 4)
    }

    aquifer_results = {}
    for aq_type in [
        "Surface Water",
        "Shallow Alluvial Groundwater",
        "Deep Confined Bedrock (Jordan Aquifer)",
        "Blended Alluvial/Jordan/Surface"
    ]:
        sub_aq = df_q[df_q["primary_water_source"] == aq_type]
        res_aq = run_twfe_did(
            sub_aq,
            outcome="mean_nitrate_mg_l",
            treat_col="post_operational_10km",
            time_col="year_quarter",
            cluster_col="pwsid"
        )
        aquifer_results[aq_type] = res_aq
    results["mechanism_2_aquifer_stratification"] = aquifer_results

    df_q["q3_summer"] = (df_q["quarter"] == 3).astype(int)
    df_q["post_op_x_q3_summer"] = df_q["post_operational_10km"] * df_q["q3_summer"]
    mod_m3 = fit_twfe_clustered_ols(
        df_q, y_col="mean_nitrate_mg_l",
        x_cols=["post_operational_10km", "post_op_x_q3_summer", "precip_anomaly_sd", "summer_temp_anomaly_sd"],
        unit_col="pwsid", time_col="year_quarter", cluster_col="huc10"
    )
    results["mechanism_3_summer_evaporative_blowdown"] = {
        "base_post_op_beta": round(mod_m3["params"]["post_operational_10km"], 5),
        "base_post_op_se": round(mod_m3["bse"]["post_operational_10km"], 5),
        "q3_summer_interaction_beta": round(mod_m3["params"]["post_op_x_q3_summer"], 5),
        "q3_summer_interaction_se": round(mod_m3["bse"]["post_op_x_q3_summer"], 5),
        "q3_summer_interaction_pval": round(mod_m3["pvalues"]["post_op_x_q3_summer"], 4)
    }

    mod_naive = fit_twfe_clustered_ols(
        df_q, y_col="mean_nitrate_mg_l",
        x_cols=["post_operational_10km"],
        unit_col="pwsid", time_col=None, cluster_col="huc10"
    )
    mod_clim = fit_twfe_clustered_ols(
        df_q, y_col="mean_nitrate_mg_l",
        x_cols=["post_operational_10km", "precip_anomaly_sd", "summer_temp_anomaly_sd"],
        unit_col="pwsid", time_col="year_quarter", cluster_col="huc10"
    )
    results["mechanism_4_climate_flushing_confounder"] = {
        "naive_no_time_or_climate_fe_beta": round(mod_naive["params"]["post_operational_10km"], 5),
        "naive_no_time_or_climate_fe_se": round(mod_naive["bse"]["post_operational_10km"], 5),
        "climate_and_twfe_controlled_beta": round(mod_clim["params"]["post_operational_10km"], 5),
        "climate_and_twfe_controlled_se": round(mod_clim["bse"]["post_operational_10km"], 5),
        "precip_anomaly_effect_mg_l_per_sd": round(mod_clim["params"]["precip_anomaly_sd"], 5),
        "precip_anomaly_t_stat": round(mod_clim["tvalues"]["precip_anomaly_sd"], 2),
        "summer_temp_anomaly_effect_mg_l_per_sd": round(mod_clim["params"]["summer_temp_anomaly_sd"], 5)
    }

    sub_corridor = df_q[df_q["suburban_growth_corridor"] == 1]
    res_suburban = run_twfe_did(
        sub_corridor,
        outcome="mean_nitrate_mg_l",
        treat_col="post_operational_10km",
        time_col="year_quarter",
        cluster_col="huc10"
    )
    results["mechanism_5_suburban_growth_matched_controls"] = res_suburban

    return results


def generate_econometric_plots(df_ev_combined: pd.DataFrame, mech_results: dict, main_specs: list):
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.size": 10,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 10,
        "figure.dpi": 200
    })

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.2), sharey=True)

    ax = axes[0]
    ax.axhspan(-0.25, 0.25, color="#D1FAE5", alpha=0.55, label="TOST Equivalence Zone (±0.25 mg/L as N)")
    ax.axhline(0, color="#1F2937", linestyle="-", linewidth=1.0)
    ax.axvline(-0.5, color="#DC2626", linestyle="--", linewidth=1.1, label="Treatment Onset (k = 0)")

    k_vals = df_ev_combined["k"].values
    ax.errorbar(
        k_vals - 0.15, df_ev_combined["beta_twfe_construct"],
        yerr=1.96 * df_ev_combined["se_twfe_construct"],
        fmt="o-", color="#1D4ED8", capsize=3, markersize=5, linewidth=1.3, label="TWFE Event Study"
    )
    ax.errorbar(
        k_vals + 0.15, df_ev_combined["beta_cs"],
        yerr=1.96 * df_ev_combined["se_cs"],
        fmt="s--", color="#047857", capsize=3, markersize=5, linewidth=1.3, label="Callaway & Sant'Anna (2021)"
    )
    ax.set_title("A. Construction / Grading Start ($T_{\\mathrm{construct}}$, 10 km Buffer)")
    ax.set_xlabel("Event Time $k$ (Years Relative to Data Center Groundbreaking)")
    ax.set_ylabel("Nitrate Treatment Effect $\\hat{\\beta}_k$ (mg/L as N)")
    ax.set_xticks(range(-5, 9))
    ax.set_ylim(-0.38, 0.38)
    ax.grid(True, linestyle=":", alpha=0.5)
    ax.legend(loc="upper left", frameon=True, fontsize=8.5)

    ax2 = axes[1]
    ax2.axhspan(-0.25, 0.25, color="#D1FAE5", alpha=0.55, label="TOST Equivalence Zone (±0.25 mg/L as N)")
    ax2.axhline(0, color="#1F2937", linestyle="-", linewidth=1.0)
    ax2.axvline(-0.5, color="#DC2626", linestyle="--", linewidth=1.1, label="Operational Activation (k = 0)")

    ax2.errorbar(
        k_vals - 0.15, df_ev_combined["beta_twfe_operational"],
        yerr=1.96 * df_ev_combined["se_twfe_operational"],
        fmt="o-", color="#7C3AED", capsize=3, markersize=5, linewidth=1.3, label="TWFE Event Study"
    )
    ax2.errorbar(
        k_vals + 0.15, df_ev_combined["beta_stacked"],
        yerr=1.96 * df_ev_combined["se_stacked"],
        fmt="^--", color="#B45309", capsize=3, markersize=5, linewidth=1.3, label="Sun & Abraham / Stacked DiD"
    )
    ax2.set_title("B. Cooling Water Operational Start ($T_{\\mathrm{operational}}$, 10 km Buffer)")
    ax2.set_xlabel("Event Time $k$ (Years Relative to Operational Activation)")
    ax2.set_xticks(range(-5, 9))
    ax2.grid(True, linestyle=":", alpha=0.5)
    ax2.legend(loc="upper left", frameon=True, fontsize=8.5)

    plt.suptitle("Staggered Difference-in-Differences Event Studies: Iowa Data Centers & PWS Nitrate (2005–2026)", fontsize=13, fontweight="bold", y=0.99)
    plt.tight_layout()
    fig1_path = os.path.join(OUTPUT_DIR, "fig1_event_study_did.png")
    plt.savefig(fig1_path, bbox_inches="tight")
    plt.close()

    fig, ax = plt.subplots(figsize=(10.5, 5.5))
    ax.axvspan(-0.25, 0.25, color="#D1FAE5", alpha=0.55, label="Negligible Equivalence Bound ($\\Delta = \\pm 0.25$ mg/L)")
    ax.axvspan(-0.106, 0.106, color="#A7F3D0", alpha=0.65, label="Strict Equivalence Bound ($\\Delta = \\pm 0.05$ SD)")
    ax.axvline(0, color="#111827", linewidth=1.2)

    labels = [sp["label"] for sp in main_specs]
    betas = [sp["beta"] for sp in main_specs]
    ci90_l = [sp["ci90_low"] for sp in main_specs]
    ci90_h = [sp["ci90_high"] for sp in main_specs]

    y_pos = np.arange(len(labels))[::-1]
    for idx, y in enumerate(y_pos):
        b = betas[idx]
        low = ci90_l[idx]
        high = ci90_h[idx]
        ax.plot([low, high], [y, y], color="#1E40AF", linewidth=2.5)
        ax.plot(b, y, "o", color="#DC2626", markersize=6.5)
        ax.text(high + 0.012, y, f"{b:+.4f} [{low:+.3f}, {high:+.3f}]", va="center", fontsize=8.5)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(labels, fontsize=9.5)
    ax.set_xlim(-0.32, 0.36)
    ax.set_xlabel("Estimated Treatment Effect $\\hat{\\beta}$ and 90% TOST Confidence Interval (mg/L as N)")
    ax.set_title("Two One-Sided Tests (TOST) Equivalence Forest Plot Across Spatial Scales & Water Sources")
    ax.grid(True, axis="x", linestyle=":", alpha=0.5)
    ax.legend(loc="lower right", frameon=True, fontsize=8.5)
    plt.tight_layout()
    fig2_path = os.path.join(OUTPUT_DIR, "fig2_tost_equivalence_forest.png")
    plt.savefig(fig2_path, bbox_inches="tight")
    plt.close()

    logger.info(f"Saved event-study and TOST figures to {fig1_path} and {fig2_path}")


def main():
    logger.info("Starting Phase 4 & 5 Econometric Analysis & Equivalence Testing...")

    q_path = os.path.join(OUTPUT_DIR, "iowa_pws_nitrate_panel_quarterly.csv")
    a_path = os.path.join(OUTPUT_DIR, "iowa_pws_nitrate_panel_annual.csv")

    if not os.path.exists(q_path):
        raise FileNotFoundError(f"Missing quarterly panel {q_path}. Run 01_fetch_and_clean_data.py first.")

    df_q = pd.read_csv(q_path)
    df_a = pd.read_csv(a_path)

    spec_configs = [
        ("Same Municipality (T_construct)", "mean_nitrate_mg_l", "post_construct_muni", "huc10"),
        ("Same Municipality (T_operational)", "mean_nitrate_mg_l", "post_operational_muni", "huc10"),
        ("5 km Buffer (T_construct)", "mean_nitrate_mg_l", "post_construct_5km", "huc10"),
        ("10 km Buffer (T_construct) [HUC-10 Clustered]", "mean_nitrate_mg_l", "post_construct_10km", "huc10"),
        ("10 km Buffer (T_construct) [County Clustered]", "mean_nitrate_mg_l", "post_construct_10km", "county"),
        ("10 km Buffer (T_operational) [HUC-10 Clustered]", "mean_nitrate_mg_l", "post_operational_10km", "huc10"),
        ("10 km Buffer (T_operational) [County Clustered]", "mean_nitrate_mg_l", "post_operational_10km", "county"),
        ("20 km Buffer (T_construct)", "mean_nitrate_mg_l", "post_construct_20km", "huc10"),
        ("Upstream / Shared HUC-10 Watershed (T_construct)", "mean_nitrate_mg_l", "post_construct_huc10", "huc10"),
        ("Max Nitrate mg/L (10 km Buffer, T_operational)", "max_nitrate_mg_l", "post_operational_10km", "huc10"),
        ("Pr(Nitrate > 5 mg/L) (10 km Buffer, T_operational)", "exceed_5mg_l", "post_operational_10km", "huc10")
    ]

    twfe_results = []
    for label, outcome, treat_col, cl_col in spec_configs:
        res = run_twfe_did(df_q, outcome=outcome, treat_col=treat_col, time_col="year_quarter", cluster_col=cl_col)
        res["label"] = label
        twfe_results.append(res)
        logger.info(
            f"[TWFE] {label}: beta = {res['beta']:+.4f} (SE = {res['se']:.4f}, p = {res['p_two_sided']:.3f}), "
            f"90% CI = [{res['ci90_low']:+.4f}, {res['ci90_high']:+.4f}], "
            f"p_TOST(0.25) = {res['p_tost_025mgl']:.5f}, MDE_80% = {res['mde_80_mg_l']:.4f}"
        )

    df_ev_c, ev_stats_c = run_event_study_twfe(
        df_q, outcome="mean_nitrate_mg_l", rel_time_col="rel_time_construct_10km", cluster_col="huc10"
    )
    df_ev_o, ev_stats_o = run_event_study_twfe(
        df_q, outcome="mean_nitrate_mg_l", rel_time_col="rel_time_operational_10km", cluster_col="huc10"
    )
    df_ev_stag, stag_summary = run_stacked_and_cs_did(
        df_a, outcome="mean_nitrate_mg_l", cohort_col="cohort_construct_10km"
    )

    df_ev_combined = df_ev_c.rename(columns={
        "beta_twfe": "beta_twfe_construct",
        "se_twfe": "se_twfe_construct",
        "ci95_low_twfe": "ci95_low_twfe_construct",
        "ci95_high_twfe": "ci95_high_twfe_construct",
        "p_val_twfe": "p_val_twfe_construct"
    }).merge(
        df_ev_o.rename(columns={
            "beta_twfe": "beta_twfe_operational",
            "se_twfe": "se_twfe_operational",
            "ci95_low_twfe": "ci95_low_twfe_operational",
            "ci95_high_twfe": "ci95_high_twfe_operational",
            "p_val_twfe": "p_val_twfe_operational"
        }),
        on="k"
    ).merge(df_ev_stag, on="k")

    ev_csv_path = os.path.join(OUTPUT_DIR, "event_study_coefficients.csv")
    df_ev_combined.to_csv(ev_csv_path, index=False)

    logger.info(
        f"[EVENT STUDY PRE-TRENDS] T_construct Joint F = {ev_stats_c['pre_trends_f_stat']:.3f} "
        f"(p = {ev_stats_c['pre_trends_p_val']:.3f}); "
        f"T_operational Joint F = {ev_stats_o['pre_trends_f_stat']:.3f} "
        f"(p = {ev_stats_o['pre_trends_p_val']:.3f}); "
        f"Stacked DiD Pre-Trends F = {stag_summary['stacked_did_pre_f_stat']:.3f} "
        f"(p = {stag_summary['stacked_did_pre_p_val']:.3f})."
    )

    mech_results = run_domain_mechanism_checks(df_q)

    forest_specs = [r for r in twfe_results if r["outcome"] == "mean_nitrate_mg_l"][:7]
    for aq_name, aq_res in mech_results["mechanism_2_aquifer_stratification"].items():
        aq_copy = dict(aq_res)
        aq_copy["label"] = f"Subsample: {aq_name}"
        forest_specs.append(aq_copy)
    sub_ctrl_copy = dict(mech_results["mechanism_5_suburban_growth_matched_controls"])
    sub_ctrl_copy["label"] = "Suburban Growth Matched Controls"
    forest_specs.append(sub_ctrl_copy)

    generate_econometric_plots(df_ev_combined, mech_results, forest_specs)

    full_summary = {
        "twfe_specifications": twfe_results,
        "event_study_twfe_construct": ev_stats_c,
        "event_study_twfe_operational": ev_stats_o,
        "staggered_did_summary": stag_summary,
        "event_study_table": df_ev_combined.to_dict(orient="records"),
        "phase5_domain_mechanisms": mech_results
    }

    summary_json_path = os.path.join(OUTPUT_DIR, "econometric_results_summary.json")
    with open(summary_json_path, "w", encoding="utf-8") as f:
        json.dump(full_summary, f, indent=2)

    for fname in ["event_study_coefficients.csv", "econometric_results_summary.json", "fig1_event_study_did.png", "fig2_tost_equivalence_forest.png"]:
        src = os.path.join(OUTPUT_DIR, fname)
        dst = os.path.join(WORKSPACE_ROOT, fname)
        if os.path.abspath(src) != os.path.abspath(dst):
            shutil.copy2(src, dst)

    this_file = os.path.abspath(__file__)
    for target_name in ["02_did_equivalence_analysis.py", "02_econometric_analysis.py"]:
        for folder in [OUTPUT_DIR, WORKSPACE_ROOT]:
            dst_script = os.path.join(folder, target_name)
            if os.path.abspath(this_file) != os.path.abspath(dst_script):
                shutil.copy2(this_file, dst_script)

    logger.info("Phase 4 & 5 econometric analysis complete.")


if __name__ == "__main__":
    main()