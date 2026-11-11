"""Observed-data analysis: descriptive coverage, stacked event-based DiD with randomization
inference, the original specification re-run on observed outcomes, and mass-balance bounds.

Inputs : data/clean/*.csv, data/reference/*, audit/original_linked_exposure.csv
Outputs: results/results.json, results/tables/*.csv, results/figures/*.png|svg

Design (pre-specified in the manuscript, Methods):
  Events  = first construction start of a documented hyperscale campus during 2013-2019, so that
            at least one pre-event year exists in EPA SYR4 (2012-2019): Meta Altoona 2013,
            Microsoft Alluvion 2014, Microsoft Osmium 2018. Earlier starts (Google 2007, Microsoft
            Mountain 2010, Google Southlands 2012) have no observed baseline and are excluded.
  Treated = for each event, the host utility, or monitored municipal systems within R km.
  Controls= geocoded systems >30 km from every documented campus and not a host.
  Outcome = annual mean entry-point nitrate (mg/L as N); non-detects at limit/sqrt(2), bounds
            as sensitivity. Missing years stay missing.
  Estimator = stacked imputation DiD (event-specific unit and year effects fitted on untreated
            observations only), equal weight per treated unit-year.
  Inference = Fisher randomization inference that re-sites each event at a random candidate
            location (Iowa places >= 2,000 residents, plus the real sites) and recomputes the
            estimator; confidence sets by inverting the sharp null of a constant additive effect.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nitrate_lib import (haversine, twoway_fit, demean_twoway, build_stack, event_study,  # noqa: E402
                         did_static, tost, ri_pvalue, cr1_static)

ROOT = Path(__file__).resolve().parents[1]
RES, TAB, FIG = ROOT / "results", ROOT / "results/tables", ROOT / "results/figures"
SEED = 20261111
B_MAIN, B_SENS = 2000, 1000
WINDOW = (-6, 6)
MARGINS = (0.5, 1.0)
TAU_GRID = np.round(np.arange(-6.0, 6.0001, 0.005), 3)
COL = {"blue": "#2a78d6", "orange": "#eb6834", "aqua": "#1baf7a", "ink": "#0b0b0b",
       "ink2": "#52514e", "grid": "#e4e3df", "muted": "#9a9893"}


# ----------------------------------------------------------------------------- data

def load():
    p = pd.read_csv(ROOT / "data/clean/nitrate_annual_panel.csv")
    p = p.loc[p.stage.eq("entry")].copy()
    ex = pd.read_csv(ROOT / "data/clean/exposure.csv")
    camp = pd.read_csv(ROOT / "data/reference/hyperscale_campuses.csv")
    places = pd.read_csv(ROOT / "data/raw/geonames_iowa_places.csv")
    return p, ex, camp, places


def vulnerability(p: pd.DataFrame) -> pd.Series:
    """Nitrate-informative systems: detected nitrate >= 0.5 mg/L in the common baseline year 2012."""
    b = p.loc[p.year.eq(2012)].set_index("pwsid")
    return (b.nitrate_mean_lower >= 0.5)


# ----------------------------------------------------------------------------- fast stacked estimator

class Design:
    """Holds numpy arrays for one estimation sample so that many assignments can be evaluated fast."""

    def __init__(self, panel: pd.DataFrame, sample_ids: list[str], outcomes: list[str], time_key: str = "year"):
        d = panel.loc[panel.pwsid.isin(sample_ids)].dropna(subset=outcomes[:1]).copy()
        self.ids = np.array(sorted(d.pwsid.unique()))
        self.idx = {k: i for i, k in enumerate(self.ids)}
        self.uid = d.pwsid.map(self.idx).to_numpy()
        self.year = d.year.to_numpy()
        self.tkey = pd.factorize(d[time_key])[0] if time_key != "year" else self.year - self.year.min()
        self.Y = {o: d[o].to_numpy(float) for o in outcomes}
        self.n_units = len(self.ids)
        self.df = d

    def stack(self, events: list[tuple[int, np.ndarray]]):
        """events: list of (g, treated uid array). Returns arrays for the stacked panel."""
        treated_any = np.zeros(self.n_units, bool)
        for _, tr in events:
            treated_any[tr] = True
        rows, u, t, D, k, ev, trf = [], [], [], [], [], [], []
        nt = self.tkey.max() + 1
        for e, (g, tr) in enumerate(events):
            if len(tr) == 0:
                continue
            is_tr = np.zeros(self.n_units, bool)
            is_tr[tr] = True
            kk = self.year - g
            m = (is_tr[self.uid] | ~treated_any[self.uid]) & (kk >= WINDOW[0]) & (kk <= WINDOW[1])
            r = np.flatnonzero(m)
            rows.append(r)
            u.append(e * self.n_units + self.uid[r])
            t.append(e * nt + self.tkey[r])
            D.append(is_tr[self.uid[r]] & (kk[r] >= 0))
            trf.append(is_tr[self.uid[r]])
            k.append(kk[r])
            ev.append(np.full(len(r), e))
        if not rows:
            return None
        r = np.concatenate(rows)
        uu = pd.factorize(np.concatenate(u))[0]
        tt = pd.factorize(np.concatenate(t))[0]
        return {"rows": r, "u": uu, "t": tt, "D": np.concatenate(D), "k": np.concatenate(k), "ev": np.concatenate(ev),
                "tr": np.concatenate(trf)}

    @staticmethod
    def impute(st, y):
        d = st["D"]
        if d.sum() == 0:
            return np.nan, {}
        u, t = st["u"], st["t"]
        a, b = twoway_fit(y[~d], u[~d], t[~d], tol=1e-11)
        su = np.bincount(u[~d], minlength=u.max() + 1) > 0
        stt = np.bincount(t[~d], minlength=t.max() + 1) > 0
        ok = d & su[u] & stt[t]
        if not ok.any():
            return np.nan, {}
        tau = y[ok] - a[u[ok]] - b[t[ok]]
        kk = st["k"][ok]
        byk = {int(j): float(tau[kk == j].mean()) for j in np.unique(kk)}
        return float(tau.mean()), byk

    @staticmethod
    def leads(st, y, kmin=WINDOW[0], ref=-1):
        """Pre-trend coefficients (BJS-style): untreated observations only, unit/time effects plus
        treated-unit indicators for k = kmin..-2 (k = -1 omitted)."""
        d = st["D"]
        u, t, k = st["u"][~d], st["t"][~d], st["k"][~d]
        tr = st["tr"][~d]
        ks = [j for j in range(kmin, ref) if np.any(tr & (k == j))]
        if not ks:
            return {}
        X = np.column_stack([(tr & (k == j)).astype(float) for j in ks])
        uu, tt = pd.factorize(u)[0], pd.factorize(t)[0]
        Xt = demean_twoway(X, uu, tt)
        yt = demean_twoway(y[~d][:, None], uu, tt)[:, 0]
        b, *_ = np.linalg.lstsq(Xt, yt, rcond=None)
        return {int(j): float(v) for j, v in zip(ks, b)}

    def stats(self, events, vectors: dict[str, np.ndarray], with_leads=False, size_cluster=None):
        st = self.stack(events)
        if st is None:
            return None
        out = {}
        for name, vec in vectors.items():
            out[name] = self.impute(st, vec[st["rows"]])
        if with_leads:
            out["leads"] = self.leads(st, vectors["y"][st["rows"]])
        if size_cluster is not None:
            out["cr1"] = cr1_static(vectors["y"][st["rows"]], st["D"], st["u"], st["t"], size_cluster[st["rows"]])
        out["n_treated_obs"] = int(st["D"].sum())
        out["n_treated_units"] = int(len(set(zip(st["ev"][st["D"]], st["u"][st["D"]]))))
        return out


def dcount_vector(des: Design, events) -> np.ndarray:
    """Cumulative number of real events that have started for each unit-year (constant-effect model)."""
    v = np.zeros(len(des.uid))
    for g, tr in events:
        is_tr = np.zeros(des.n_units, bool)
        is_tr[tr] = True
        v += (is_tr[des.uid] & (des.year >= g))
    return v


# ----------------------------------------------------------------------------- specification runner

def assign_events(des: Design, sites: list[tuple[int, float, float]], R: float, coords: dict):
    """Treated = sample units within R km of each (g, lat, lon) site."""
    lat = np.array([coords[i][0] for i in des.ids])
    lon = np.array([coords[i][1] for i in des.ids])
    out = []
    for g, la, lo in sites:
        d = haversine(la, lo, lat, lon)
        out.append((g, np.flatnonzero(d <= R)))
    return out


def run_spec(name, panel, ex, camp, places, *, exposure="r10", outcome="nitrate_mean", sample="all",
             controls="control_primary", year_key="year", construct="construct_start_year",
             drop_event=None, B=B_SENS, seed=SEED, keep_draws=False, exclude_units=(),
             custom_treated=None, custom_pool=None):
    rng = np.random.default_rng(seed)
    ev = camp.loc[camp[construct].between(2013, 2019)].copy()
    if drop_event:
        ev = ev.loc[ev.campus_id.ne(drop_event)]
    if custom_treated is not None:
        ev = ev.loc[ev.campus_id.isin(custom_treated)]
    ex = ex.copy()
    coords = {r.pwsid: (r.lat, r.lon) for r in ex.itertuples()}
    monitored = set(panel.pwsid)
    ctrl = set(ex.loc[ex[controls] & ex.pwsid.isin(monitored), "pwsid"])
    if custom_treated is not None:
        real_tr = {c: set(v) & monitored for c, v in custom_treated.items()}
    elif exposure == "host":
        real_tr = {r.campus_id: {r.presumed_host_pwsid} & monitored for r in ev.itertuples()}
    else:
        R = float(exposure[1:])
        real_tr = {}
        for r in ev.itertuples():
            d = haversine(r.lat, r.lon, ex.lat.values, ex.lon.values)
            real_tr[r.campus_id] = set(ex.pwsid[(d <= R) & ex.lat.notna()]) & monitored
    real_tr = {c: v - set(exclude_units) for c, v in real_tr.items()}
    ctrl = ctrl - set(exclude_units)
    treated_any = set().union(*real_tr.values()) if real_tr else set()
    sample_ids = sorted(treated_any | ctrl)
    if sample == "vulnerable":
        vul = vulnerability(panel)
        sample_ids = [i for i in sample_ids if bool(vul.get(i, False))]
    outs = [outcome]
    des = Design(panel, sample_ids, outs, time_key=year_key)
    real_events = [(int(getattr(r, construct)), np.array([des.idx[i] for i in sorted(real_tr[r.campus_id]) if i in des.idx], int))
                   for r in ev.itertuples()]
    if sum(len(t) for _, t in real_events) == 0:
        return {"spec": name, "status": "no treated units"}
    dvec = dcount_vector(des, real_events)
    Y = des.Y[outcome]
    gcl = pd.factorize(des.df.pwsid.map(ex.set_index("pwsid").county).fillna("NA"))[0]
    extra = dict(with_leads=keep_draws, size_cluster=gcl if keep_draws else None)
    obs = des.stats(real_events, {"y": Y, "d": dvec}, **extra)
    att, byk = obs["y"]
    c_obs, _ = obs["d"]
    lead_obs = obs.get("leads", {})

    # ---- placebo assignment generators (the real assignment is one of the possible draws)
    if custom_treated is not None:
        pool = np.array([des.idx[i] for i in (custom_pool or []) if i in des.idx])
        def draw():
            return [(int(getattr(r, construct)), np.array([pool[rng.integers(len(pool))]])) for r in ev.itertuples()]
    elif exposure == "host":
        pop = ex.set_index("pwsid").population_served
        cand = [i for i in des.ids if pop.get(i, 0) >= 2000 and (i in ctrl or i in treated_any)]
        cand_idx = np.array([des.idx[i] for i in cand])
        operators = sorted(set(ev.operator))
        def draw():
            host_by_op = {op: cand_idx[rng.integers(len(cand_idx))] for op in operators}
            return [(int(getattr(r, construct)), np.array([host_by_op[r.operator]])) for r in ev.itertuples()]
    else:
        R = float(exposure[1:])
        lat = np.array([coords[i][0] for i in des.ids]); lon = np.array([coords[i][1] for i in des.ids])
        cand = places.loc[places.population_geonames >= 2000, ["lat", "lon"]].to_numpy()
        cand = np.vstack([cand, ev[["lat", "lon"]].to_numpy()])
        has_unit = np.array([(haversine(a, b, lat, lon) <= R).any() for a, b in cand])
        cand = cand[has_unit]
        def draw():
            pick = cand[rng.integers(len(cand), size=len(ev))]
            return [(int(getattr(r, construct)), np.flatnonzero(haversine(pk[0], pk[1], lat, lon) <= R))
                    for r, pk in zip(ev.itertuples(), pick)]
    draws_y, draws_d, draws_k, draws_lead, cr1_p = [], [], [], [], []
    for _ in range(B):
        s = des.stats(draw(), {"y": Y, "d": dvec}, **extra)
        if s is None:
            continue
        draws_y.append(s["y"][0]); draws_d.append(s["d"][0]); draws_k.append(s["y"][1])
        if keep_draws:
            draws_lead.append(s.get("leads", {})); cr1_p.append(s["cr1"][1])
    zy, zd = np.array(draws_y), np.array(draws_d)
    ok = np.isfinite(zy) & np.isfinite(zd)
    zy, zd = zy[ok], zd[ok]
    p0 = ri_pvalue(att, zy)
    pv = np.array([(1 + np.sum(np.abs(zy - tau * zd) >= np.abs(att - tau * c_obs) - 1e-12)) / (1 + len(zy))
                   for tau in TAU_GRID])
    def ci(alpha):
        acc = TAU_GRID[pv > alpha]
        if len(acc) == 0:
            return [np.nan, np.nan]
        lo, hi = float(acc.min()), float(acc.max())
        open_lo, open_hi = lo <= TAU_GRID.min() + 1e-9, hi >= TAU_GRID.max() - 1e-9
        return [None if open_lo else lo, None if open_hi else hi]
    ci90, ci95 = ci(0.10), ci(0.05)
    crit = np.quantile(np.abs(zy - np.median(zy)), 0.95)
    mde = None
    for tau in np.arange(0.0, 6.0, 0.01):
        if np.mean(np.abs(zy - np.median(zy) + tau) > crit) >= 0.80:
            mde = round(float(tau), 2)
            break
    eq = {f"equivalent_within_{m}": (ci90[0] is not None and ci90[1] is not None and -m < ci90[0] and ci90[1] < m)
          for m in MARGINS}
    # descriptive comparison: static stacked TWFE with county-cluster SE (not used for inference)
    st = des.stack(real_events)
    sdf = des.df.iloc[st["rows"]].reset_index(drop=True).assign(u=st["u"], t=st["t"], D=st["D"].astype(int))
    sdf["county"] = sdf.pwsid.map(ex.set_index("pwsid").county)
    tw = did_static(sdf, outcome, "county")
    res = {
        "spec": name, "exposure": exposure, "outcome": outcome, "sample": sample, "controls": controls,
        "time_fe": year_key, "construct_year": construct, "dropped_event": drop_event,
        "events": [{"campus": r.campus_id, "g": int(getattr(r, construct)),
                    "treated": sorted(real_tr[r.campus_id] & set(des.ids))} for r in ev.itertuples()],
        "n_units": int(des.n_units), "n_control_units": int(len(set(des.ids) - treated_any)),
        "n_treated_units_distinct": int(len(treated_any & set(des.ids))),
        "n_treated_obs": obs["n_treated_obs"], "att": att, "att_by_k": byk,
        "ri_draws": int(len(zy)), "ri_p": p0, "ri_ci90": ci90, "ri_ci95": ci95,
        "placebo_sd": float(np.std(zy, ddof=1)), "mde80_ri": mde, **eq,
        "twfe_county_cluster": tw,
    }
    if keep_draws:
        res["_draws_y"], res["_draws_k"], res["_c_obs"], res["_draws_d"] = zy, draws_k, c_obs, zd
        res["_draws_lead"] = draws_lead
        res["leads"] = lead_obs
        cp = np.array(cr1_p, float)
        cp = cp[np.isfinite(cp)]
        res["conventional_cr1_county_rejection_rate_under_placebo"] = {
            "alpha_0_05": float(np.mean(cp < 0.05)), "alpha_0_10": float(np.mean(cp < 0.10)), "draws": int(len(cp))}
    return res


# ----------------------------------------------------------------------------- original spec on observed data

def original_spec_observed(panel, rng_seed=SEED, B=5000):
    lk = pd.read_csv(ROOT / "audit/original_linked_exposure.csv", dtype={"huc10": str, "huc8": str})
    d = panel.merge(lk[["pwsid", "huc10", "county", "cohort_construct_10km", "cohort_operational_10km"]],
                    on="pwsid", how="inner")
    out = {}
    for treat in ["cohort_construct_10km", "cohort_operational_10km"]:
        x = d.copy()
        x["D"] = (x[treat].notna() & (x.year >= x[treat])).astype(int)
        x["u"] = pd.factorize(x.pwsid)[0]
        x["t"] = pd.factorize(x.year)[0]
        r = did_static(x, "nitrate_mean", "huc10")
        ys = x.nitrate_mean.std()
        t_ = tost(r["beta"], r["se"], r["G"] - 1, 0.25)
        coh = lk.set_index("pwsid")[treat].reindex(x.pwsid.unique())
        switchers = int(((coh > 2012) & (coh <= 2019)).sum())
        always = int((coh <= 2012).sum())
        # randomization inference: permute cohort years across the 38 systems
        rng = np.random.default_rng(rng_seed)
        ids = x.pwsid.unique()
        cvals = coh.to_numpy()
        zs = []
        for _ in range(B):
            perm = dict(zip(ids, rng.permutation(cvals)))
            gg = x.pwsid.map(perm)
            Dp = (gg.notna() & (x.year >= gg)).astype(float).to_numpy()
            yt = demean_twoway(x.nitrate_mean.to_numpy()[:, None], x.u.to_numpy(), x.t.to_numpy())[:, 0]
            dt = demean_twoway(Dp[:, None], x.u.to_numpy(), x.t.to_numpy())[:, 0]
            zs.append(float(dt @ yt / (dt @ dt)) if (dt @ dt) > 1e-12 else np.nan)
        out[treat] = {"beta": r["beta"], "se_cr1_huc10": r["se"], "p_cr1": r["p"], "n_obs": r["n"],
                      "n_clusters": r["G"], "n_systems": int(x.pwsid.nunique()), "outcome_sd": float(ys),
                      "tost_0_25": t_, "systems_switching_2013_2019": switchers,
                      "systems_already_treated_by_2012": always,
                      "ri_p_permute_cohorts": ri_pvalue(r["beta"], np.array(zs)),
                      "mde80_cr1": float((2.0 + 0.84) * r["se"])}
    return out


# ----------------------------------------------------------------------------- mass balance

def mass_balance():
    mb = json.loads((ROOT / "data/reference/mass_balance_inputs.json").read_text())
    cv = mb["unit_conversions"]
    sc = mb["export_scenarios_kg_ha_yr"]
    rows = []
    def add(river, flow_label, cfs, area_label, acres):
        q = cfs * cv["cfs_to_m3_s"] * cv["seconds_per_year"]  # m3/yr
        ha = acres * cv["acre_to_ha"]
        for lab, ex in [("construction_extreme", sc["construction_extreme"]),
                        ("construction_implausible_ceiling", sc["construction_implausible_ceiling"]),
                        ("post_development_low_input", sc["post_development_low_input"])]:
            net = (ex - sc["row_crop_counterfactual"]) * ha  # kg N/yr relative to row crops
            rows.append({"river": river, "flow_statistic": flow_label, "flow_cfs": cfs, "area_scenario": area_label,
                         "acres": acres, "export_scenario": lab, "export_kg_ha_yr": ex,
                         "net_load_kg_yr": round(net, 1), "delta_conc_mg_l": net / q * 1000.0,
                         "gross_load_kg_yr": round(ex * ha, 1), "gross_conc_mg_l": ex * ha / q * 1000.0})
    r = mb["rivers"]["raccoon_van_meter"]
    for fl, cfs in [("mean", r["mean_flow_cfs"]), ("median", r["median_flow_cfs"]), ("Q90 1916-2004", r["q90_flow_cfs"])]:
        for k in ["raccoon_documented_central_iowa", "raccoon_with_full_apple_site"]:
            add("Raccoon (Van Meter)", fl, cfs, k, mb["campus_area_scenarios_acres"][k]["acres"])
        add("Raccoon (Van Meter)", fl, cfs, "per_1000_acres", 1000.0)
    m = mb["rivers"]["missouri_omaha"]
    for fl, cfs in [("median", m["median_flow_cfs"]), ("5th percentile", m["p05_flow_cfs"])]:
        add("Missouri (Omaha)", fl, cfs, "missouri_google_documented", mb["campus_area_scenarios_acres"]["missouri_google_documented"]["acres"])
    c = mb["rivers"]["cedar_cedar_rapids"]
    for fl, cfs in [("mean", c["mean_flow_cfs"]), ("Q90 WY2004", c["q90_flow_cfs_wy2004"])]:
        add("Cedar (Cedar Rapids)", fl, cfs, "per_1000_acres", 1000.0)
    df = pd.DataFrame(rows)
    basin_ha = r["drainage_area_sq_mi"] * 258.999
    share = mb["campus_area_scenarios_acres"]["raccoon_documented_central_iowa"]["acres"] * cv["acre_to_ha"] / basin_ha
    return df, {"raccoon_basin_ha": basin_ha, "documented_campus_share_of_basin": share,
                "basin_mean_load_kg_yr": basin_ha * r["nitrate_n_yield_kg_ha_yr"]}


# ----------------------------------------------------------------------------- figures

def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    for s in ["left", "bottom"]:
        ax.spines[s].set_color(COL["muted"])
    ax.tick_params(colors=COL["ink2"], labelsize=9)
    ax.grid(axis="y", color=COL["grid"], lw=0.8)
    ax.set_axisbelow(True)


def fig_host_series(panel, ex, camp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    hosts = [("IA7727031", "Des Moines Water Works (surface)"), ("IA7785007", "West Des Moines Water Works"),
             ("IA7820080", "Council Bluffs Water Works"), ("IA7707030", "Altoona Water Supply")]
    events = {"IA7785007": [("Alluvion", 2014), ("Osmium", 2018)], "IA7707030": [("Meta", 2013)],
              "IA7820080": [("Southlands", 2012)], "IA7727031": []}
    ctrl = panel.loc[panel.pwsid.isin(ex.loc[ex.control_primary, "pwsid"])]
    cm = ctrl.groupby("year").nitrate_mean.median()
    fig, axs = plt.subplots(2, 2, figsize=(9.2, 6.0), sharex=True)
    for ax, (pid, lab) in zip(axs.ravel(), hosts):
        s = panel.loc[panel.pwsid.eq(pid)].sort_values("year")
        ax.fill_between(s.year, s.nitrate_mean_lower, s.nitrate_mean_upper, color=COL["blue"], alpha=0.15, lw=0)
        ax.plot(s.year, s.nitrate_mean, "-o", color=COL["blue"], lw=2, ms=5, label="System (entry point)")
        ax.plot(cm.index, cm.values, "--", color=COL["ink2"], lw=1.5, label="Median of control systems")
        for nm, g in events[pid]:
            ax.axvline(g, color=COL["orange"], lw=1.2)
            ax.text(g + 0.08, ax.get_ylim()[1] * 0.92 if ax.get_ylim()[1] > 0 else 1, nm, color=COL["ink2"], fontsize=8)
        ax.set_title(lab, fontsize=10, color=COL["ink"], loc="left")
        style(ax)
        ax.set_ylim(bottom=0)
    for ax in axs[:, 0]:
        ax.set_ylabel("Nitrate, mg/L as N", fontsize=9, color=COL["ink2"])
    axs[0, 0].legend(fontsize=8, frameon=False, loc="upper left")
    fig.text(0.01, 0.005, "Shaded band: range implied by treating non-detects as 0 vs. the reporting limit. "
             "Orange lines: documented construction starts of new campuses. Source: EPA SYR4.",
             fontsize=7.5, color=COL["ink2"])
    fig.tight_layout(rect=(0, 0.03, 1, 1))
    fig.savefig(FIG / "fig2_host_utility_series.png", dpi=220)
    fig.savefig(FIG / "fig2_host_utility_series.svg")
    plt.close(fig)


def fig_event_study(es_rows, path_stub, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = pd.DataFrame(es_rows).sort_values("k")
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ax.axhspan(-1.0, 1.0, color=COL["grid"], alpha=0.6, lw=0, label="±1.0 mg/L reference band")
    ax.axhline(0, color=COL["muted"], lw=1)
    ax.axvline(-0.5, color=COL["muted"], lw=1, ls=":")
    pre = d.k < 0
    ax.errorbar(d.k[pre], d.beta[pre], yerr=[d.beta[pre] - d.lo[pre], d.hi[pre] - d.beta[pre]], fmt="o",
                color=COL["ink2"], ms=6, lw=1.5, capsize=0, label="Pre-event placebo leads (k = −1 omitted)")
    ax.errorbar(d.k[~pre], d.beta[~pre], yerr=[d.beta[~pre] - d.lo[~pre], d.hi[~pre] - d.beta[~pre]], fmt="o",
                color=COL["blue"], ms=6, lw=1.5, capsize=0, label="Post-event effects (imputation)")
    ax.text(0.99, 0.02, "Bars: 95% randomization intervals", transform=ax.transAxes, ha="right", va="bottom",
            fontsize=7.5, color=COL["ink2"])
    ax.set_xlabel("Years relative to construction start", fontsize=9, color=COL["ink2"])
    ax.set_ylabel("Effect on nitrate, mg/L as N", fontsize=9, color=COL["ink2"])
    ax.set_title(title, fontsize=10, color=COL["ink"], loc="left")
    style(ax)
    ax.legend(fontsize=8, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.17), ncol=3)
    fig.tight_layout()
    fig.savefig(FIG / f"{path_stub}.png", dpi=220)
    fig.savefig(FIG / f"{path_stub}.svg")
    plt.close(fig)


def fig_spec_curve(rows, path_stub):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    d = pd.DataFrame(rows)
    d = d.loc[d.att.notna()].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(7.6, 0.32 * len(d) + 1.2))
    y = np.arange(len(d))[::-1]
    ax.axvspan(-1, 1, color=COL["grid"], alpha=0.6, lw=0)
    ax.axvspan(-0.5, 0.5, color=COL["grid"], alpha=0.9, lw=0)
    ax.axvline(0, color=COL["muted"], lw=1)
    lo = d.ci95_lo.fillna(-3.2).to_numpy(); hi = d.ci95_hi.fillna(3.2).to_numpy()
    ax.hlines(y, lo, hi, color=COL["blue"], lw=2)
    ax.plot(d.att, y, "o", color=COL["blue"], ms=6)
    ax.set_yticks(y)
    ax.set_yticklabels(d.label, fontsize=8, color=COL["ink"])
    ax.set_xlim(-3.3, 3.3)
    ax.set_xlabel("Effect on annual mean nitrate, mg/L as N (randomization 95% confidence set)", fontsize=9, color=COL["ink2"])
    style(ax)
    ax.grid(axis="y", visible=False)
    ax.grid(axis="x", color=COL["grid"], lw=0.8)
    fig.tight_layout()
    fig.savefig(FIG / f"{path_stub}.png", dpi=220)
    fig.savefig(FIG / f"{path_stub}.svg")
    plt.close(fig)


def fig_map(ex, panel, camp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    g = ex.dropna(subset=["lat"])
    mon = g.pwsid.isin(panel.pwsid)
    fig, ax = plt.subplots(figsize=(7.6, 5.0))
    c = g.loc[g.control_primary & mon]
    o = g.loc[~g.control_primary & mon]
    ax.plot(c.lon, c.lat, "o", ms=3.5, color=COL["muted"], alpha=0.7, label=f"Control systems (n={len(c)})")
    ax.plot(o.lon, o.lat, "o", ms=5, color=COL["blue"], label=f"Systems ≤30 km of a campus or host (n={len(o)})")
    a = camp.loc[camp.verification_tier.eq("A")]
    ax.plot(a.lon, a.lat, "^", ms=9, color=COL["orange"], mec="white", mew=1.0, label="Documented hyperscale campus")
    names = {"GOOG_CB1": "Google CB-1 2007", "GOOG_CB2": "Google Southlands 2012", "MSFT_MTN": "MS Mountain 2010",
             "MSFT_ALV": "MS Alluvion 2014", "MSFT_OSM": "MS Osmium 2018", "META_ALT": "Meta Altoona 2013",
             "APPL_WAU": "Apple Waukee 2021"}
    offs = {"GOOG_CB1": (-10, 14), "GOOG_CB2": (10, -10), "MSFT_MTN": (-95, 22), "MSFT_ALV": (40, -28),
            "MSFT_OSM": (-40, -40), "META_ALT": (30, 30), "APPL_WAU": (-75, 38)}
    for r in a.itertuples():
        ax.annotate(names[r.campus_id], (r.lon, r.lat), xytext=offs[r.campus_id], textcoords="offset points",
                    fontsize=7, color=COL["ink"], arrowprops=dict(arrowstyle="-", color=COL["muted"], lw=0.7))
    ax.set_xlim(-96.7, -90.1); ax.set_ylim(40.35, 43.55)
    ax.set_aspect(1 / np.cos(np.radians(42)))
    ax.set_xlabel("Longitude", fontsize=9, color=COL["ink2"]); ax.set_ylabel("Latitude", fontsize=9, color=COL["ink2"])
    style(ax)
    ax.legend(fontsize=7.5, frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=3)
    fig.tight_layout()
    fig.savefig(FIG / "fig1_study_map.png", dpi=220)
    fig.savefig(FIG / "fig1_study_map.svg")
    plt.close(fig)


# ----------------------------------------------------------------------------- main

def main() -> None:
    for d in (RES, TAB, FIG):
        d.mkdir(parents=True, exist_ok=True)
    panel, ex, camp, places = load()
    ex_cols = ["pwsid", "region"]
    panel = panel.merge(ex[ex_cols], on="pwsid", how="left")
    panel["region_year"] = panel.region.fillna("NA") + "_" + panel.year.astype(str)
    swt = ex.set_index("pwsid").source_water_type.map({"GW": "GW", "SW": "SW", "GU": "SW"})
    panel["source_class"] = panel.pwsid.map(swt).fillna("GW")
    panel["source_year"] = panel.source_class + "_" + panel.year.astype(str)
    panel["region_source_year"] = panel.region.fillna("NA") + "_" + panel.source_year
    out: dict = {}

    # ---- descriptive
    cs = json.loads((ROOT / "data/clean/cleaning_summary.json").read_text())
    vul = vulnerability(panel)
    cov = panel.groupby("year").agg(systems=("pwsid", "nunique"), samples=("n_samples", "sum"),
                                    median_nitrate=("nitrate_mean", "median"),
                                    share_exceed5=("exceed5_lower", "mean")).reset_index()
    cov.to_csv(TAB / "coverage_by_year.csv", index=False)
    lim = pd.read_csv(ROOT / "data/clean/nitrate_samples_clean.csv", usecols=["eligible", "stage", "censored", "limit_mg_l"])
    lim = lim.loc[lim.eligible & lim.stage.eq("entry") & lim.censored]
    out["descriptive"] = {
        "cleaning": cs, "n_systems_entry_panel": int(panel.pwsid.nunique()),
        "n_system_years": int(len(panel)), "median_samples_per_system_year": float(panel.n_samples.median()),
        "share_system_years_one_sample": float((panel.n_samples == 1).mean()),
        "nondetect_limit_share_ge_1mg": float((lim.limit_mg_l >= 1.0).mean()),
        "nondetect_limit_median": float(lim.limit_mg_l.median()),
        "vulnerable_systems_2012": int(vul.sum()), "systems_with_2012_obs": int(len(vul)),
        "within_system_sd_vulnerable": float(panel.loc[panel.pwsid.isin(vul[vul].index)].groupby("pwsid").nitrate_mean.std().median()),
        "by_source_type": panel.merge(ex[["pwsid", "source_water_type"]], on="pwsid").groupby("source_water_type")
                               .agg(systems=("pwsid", "nunique"), mean=("nitrate_mean", "mean")).round(3).to_dict(),
        "geocoded_monitored": int(ex.loc[ex.lat.notna()].pwsid.isin(panel.pwsid).sum()),
        "primary_controls_monitored": int(ex.loc[ex.control_primary].pwsid.isin(panel.pwsid).sum()),
    }
    hosts = ["IA7727031", "IA7785007", "IA7820080", "IA7707030", "IA7709053", "IA7751092", "IA2570046"]
    hs = panel.loc[panel.pwsid.isin(hosts)].pivot(index="pwsid", columns="year", values="nitrate_mean").round(2)
    hs.to_csv(TAB / "selected_system_series.csv")

    # ---- main specifications (B_MAIN draws)
    main_specs = [("Host utility", dict(exposure="host")),
                  ("Within 5 km", dict(exposure="r5")),
                  ("Within 10 km", dict(exposure="r10")),
                  ("Within 15 km", dict(exposure="r15")),
                  ("Within 20 km", dict(exposure="r20"))]
    main_rows, details = [], {}
    for lab, kw in main_specs:
        r = run_spec(lab, panel, ex, camp, places, B=B_MAIN, keep_draws=(kw["exposure"] in ("r10", "r15", "host")), **kw)
        details[lab] = r
        print(lab, r.get("att"), r.get("ri_p"), r.get("ri_ci95"))
    # ---- sensitivity specifications around the 15 km and host designs
    sens = []
    for base_lab, base in [("15 km", dict(exposure="r15")), ("Host", dict(exposure="host"))]:
        variants = [
            ("nitrate-informative systems only", dict(sample="vulnerable")),
            ("non-detects at 0 (lower bound)", dict(outcome="nitrate_mean_lower")),
            ("non-detects at limit (upper bound)", dict(outcome="nitrate_mean_upper")),
            ("log nitrate", dict(outcome="log_nitrate")),
            ("any sample > 5 mg/L (probability)", dict(outcome="exceed5_lower")),
            ("region-by-year effects", dict(year_key="region_year")),
            ("source-type-by-year effects", dict(year_key="source_year")),
            ("region-by-source-by-year effects", dict(year_key="region_source_year")),
            ("exclude Des Moines Water Works", dict(exclude_units=("IA7727031",))),
            ("strict controls", dict(controls="control_strict")),
            ("earliest documented start years", dict(construct="construct_year_low")),
            ("latest documented start years", dict(construct="construct_year_high")),
            ("drop Meta Altoona", dict(drop_event="META_ALT")),
            ("drop Microsoft Alluvion", dict(drop_event="MSFT_ALV")),
            ("drop Microsoft Osmium", dict(drop_event="MSFT_OSM")),
        ]
        for vlab, kw in variants:
            spec = {**base, **kw}
            r = run_spec(f"{base_lab}: {vlab}", panel, ex, camp, places, B=B_SENS, **spec)
            sens.append(r)
            print(r["spec"], r.get("att"), r.get("ri_p"))

    # ---- negative control: Des Moines Water Works cannot receive runoff from the Meta Altoona site
    #      (its river intakes lie upstream); any 'effect' here measures bias from regional shocks.
    sw_ctrl = sorted(set(ex.loc[ex.control_primary & ex.source_water_type.isin(["SW", "GU"]), "pwsid"]) & set(panel.pwsid))
    neg = []
    for lab, kw in [("Negative control: DMWW x Meta 2013 (year effects)", dict()),
                    ("Negative control: DMWW x Meta 2013 (source-by-year effects)", dict(year_key="source_year"))]:
        kw2 = dict(custom_treated={"META_ALT": ["IA7727031"]}, custom_pool=sw_ctrl + ["IA7727031"], B=B_MAIN, **kw)
        r = run_spec(lab, panel, ex, camp, places, **kw2)
        neg.append(r)
        print(lab, r.get("att"), r.get("ri_p"), r.get("ri_ci95"))
    out["negative_control"] = neg

    def row(r, label=None):
        return {"label": label or r["spec"], "att": r.get("att"), "ri_p": r.get("ri_p"),
                "ci90_lo": (r.get("ri_ci90") or [None, None])[0], "ci90_hi": (r.get("ri_ci90") or [None, None])[1],
                "ci95_lo": (r.get("ri_ci95") or [None, None])[0], "ci95_hi": (r.get("ri_ci95") or [None, None])[1],
                "treated_units": r.get("n_treated_units_distinct"), "treated_obs": r.get("n_treated_obs"),
                "control_units": r.get("n_control_units"), "placebo_sd": r.get("placebo_sd"),
                "mde80": r.get("mde80_ri"), "equiv_0_5": r.get("equivalent_within_0.5"),
                "equiv_1_0": r.get("equivalent_within_1.0"),
                "twfe_beta": (r.get("twfe_county_cluster") or {}).get("beta"),
                "twfe_se_county": (r.get("twfe_county_cluster") or {}).get("se"),
                "twfe_p_county": (r.get("twfe_county_cluster") or {}).get("p"),
                "ri_draws": r.get("ri_draws"), "status": r.get("status", "ok")}
    main_rows = [row(details[l]) for l, _ in main_specs]
    pd.DataFrame(main_rows).to_csv(TAB / "table2_main_estimates.csv", index=False)
    pd.DataFrame([row(r) for r in sens]).to_csv(TAB / "table3_sensitivity.csv", index=False)
    pd.DataFrame([row(r) for r in neg]).to_csv(TAB / "table3b_negative_control.csv", index=False)
    out["main"] = {k: {kk: vv for kk, vv in v.items() if not kk.startswith("_")} for k, v in details.items()}
    out["sensitivity"] = [{kk: vv for kk, vv in r.items() if not kk.startswith("_")} for r in sens]

    # ---- event-study figures: pre-event leads (untreated observations, BJS-style) and post-event
    #      imputation effects; all intervals from the randomization distribution (placebo quantiles).
    es_out = {}
    for key, stub, ttl in [("Within 15 km", "fig3_event_study_15km", "Construction start within 15 km (3 events, stacked)"),
                           ("Host utility", "fig4_event_study_host", "Host utility of the new campus (3 events, stacked)")]:
        r = details[key]
        rows = []
        for k, b in sorted(r.get("leads", {}).items()):
            z = np.array([d.get(k, np.nan) for d in r["_draws_lead"]])
            z = z[np.isfinite(z)]
            if len(z) < 50:
                continue
            q = np.quantile(z - np.median(z), [0.025, 0.975])
            rows.append({"k": k, "beta": b, "lo": b - q[1], "hi": b - q[0], "n_draws": int(len(z)), "part": "lead"})
        for k, b in sorted(r["att_by_k"].items()):
            z = np.array([d.get(k, np.nan) for d in r["_draws_k"]])
            z = z[np.isfinite(z)]
            if len(z) < 50:
                continue
            q = np.quantile(z - np.median(z), [0.025, 0.975])
            rows.append({"k": k, "beta": b, "lo": b - q[1], "hi": b - q[0], "n_draws": int(len(z)), "part": "post"})
        pd.DataFrame(rows).to_csv(TAB / f"{stub}.csv", index=False)
        es_out[key] = rows
        fig_event_study(rows, stub, ttl)
    out["event_study"] = es_out

    # ---- specification curve
    spec_rows = []
    for lab, _ in main_specs:
        spec_rows.append({**row(details[lab]), "label": f"{lab} (main)"})
    for r in sens:
        if r.get("outcome") in ("log_nitrate", "exceed5_lower"):
            continue  # different units; reported in Table 3 only
        spec_rows.append(row(r))
    fig_spec_curve(spec_rows, "fig5_specification_curve")

    # ---- original specification with observed outcomes
    out["original_spec_on_observed_data"] = original_spec_observed(panel)

    # ---- mass balance
    mbdf, mbx = mass_balance()
    mbdf.to_csv(TAB / "table4_mass_balance.csv", index=False)
    out["mass_balance"] = {"summary": mbx, "rows": mbdf.round(5).to_dict(orient="records")}

    fig_map(ex, panel, camp)
    fig_host_series(panel, ex, camp)
    (RES / "results.json").write_text(json.dumps(out, indent=2, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    print(json.dumps(out["original_spec_on_observed_data"], indent=2, default=str))


if __name__ == "__main__":
    main()
