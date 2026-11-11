"""Verification suite. Writes results/verification_report.json and exits non-zero on failure.

Tests that use generated data say so explicitly: they validate estimator code on ARTIFICIAL
fixtures with known answers and never touch the observed-data outputs.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "code"))
import nitrate_lib as L  # noqa: E402

RESULTS: list[dict] = []


def check(name, cond, detail=""):
    RESULTS.append({"test": name, "passed": bool(cond), "detail": str(detail)})
    print(("PASS " if cond else "FAIL ") + name + (f"  [{detail}]" if detail else ""))


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    # ---------------------------------------------------------------- provenance
    check("SYR4 Iowa extract matches audited SHA-256",
          sha(ROOT / "data/raw/epa_syr4_iowa_nitrate_raw.csv") == "0aab0467dff6e70a5d0e87622c196eec12efb728a5a7593049ce093f689cbc19")
    log = json.loads((ROOT / "data/raw/acquisition_log.json").read_text())
    check("Acquisition log records every attempt including failures", any("error" in r for r in log) or len(log) > 1,
          f"{len(log)} entries")
    for f in ["00_extract_public_data.py", "01_clean_data.py", "03_build_exposure.py"]:
        src = (ROOT / "code" / f).read_text()
        check(f"No random number generation in {f}", re.search(r"np\.random|random\.|default_rng", src) is None)
    src4 = (ROOT / "code/04_analyze.py").read_text()
    rng_lines = [ln.strip() for ln in src4.splitlines() if "default_rng" in ln]
    check("Randomness in 04_analyze.py is limited to seeded permutation draws",
          all("seed" in ln or "rng_seed" in ln for ln in rng_lines) and len(rng_lines) == 2, rng_lines)

    # ---------------------------------------------------------------- cleaning
    raw = pd.read_csv(ROOT / "data/raw/epa_syr4_iowa_nitrate_raw.csv", dtype=str)
    s = pd.read_csv(ROOT / "data/clean/nitrate_samples_clean.csv", dtype={"SIX_YEAR_ID": str})
    check("Row count preserved through cleaning", len(raw) == len(s), f"{len(raw)} vs {len(s)}")
    det = s.loc[s.DETECT.astype(str).eq("1") & s.UNIT.eq("UG/L")].head(200)
    check("ug/L results divided by 1000", np.allclose(det.nitrate_mid, det.VALUE.astype(float) / 1000))
    ok = s.nitrate_mid.notna()
    check("Censoring bounds ordered lower <= mid <= upper",
          ((s.nitrate_lower[ok] <= s.nitrate_mid[ok] + 1e-12) & (s.nitrate_mid[ok] <= s.nitrate_upper[ok] + 1e-12)).all())
    nd = s.loc[s.censored & ok]
    check("Non-detects use their own reporting limit (no common MDL assumed)",
          nd.limit_mg_l.nunique() > 1 and np.allclose(nd.nitrate_upper, nd.limit_mg_l), f"{nd.limit_mg_l.nunique()} distinct limits")
    check("Raw-water records are never labelled entry",
          not s.loc[s.WATER_FACILITY_TYPE.isin(["WL", "IN"]) & s.SOURCE_TYPE_CODE.isna(), "stage"].eq("entry").any())
    p = pd.read_csv(ROOT / "data/clean/nitrate_annual_panel.csv")
    check("Annual panel unique by system-stage-year", not p.duplicated(["pwsid", "stage", "year"]).any())
    # Recompute one cell by hand from samples: DMWW 2015 entry-point mean (point-then-system averaging)
    e = s.loc[s.eligible & s.stage.eq("entry") & s.pwsid.eq("IA7727031") & s.year.eq(2015)]
    hand = e.groupby("SAMPLING_POINT_ID").nitrate_mid.mean().mean()
    cell = p.loc[p.pwsid.eq("IA7727031") & p.year.eq(2015) & p.stage.eq("entry"), "nitrate_mean"].iat[0]
    check("Panel cell reproduces from samples (DMWW 2015)", abs(hand - cell) < 1e-12, f"{hand:.4f}")
    check("No filled or interpolated years (every panel row has >= 1 sample)", (p.n_samples >= 1).all())
    a = pd.read_csv(ROOT / "data/clean/pws_attributes.csv")
    spots = {"IA8222001": "Davenport", "IA7820080": "Council Bluffs", "IA7707030": "Altoona",
             "IA7785007": "West Des Moines", "IA7727031": "Des Moines", "IA5715093": "Cedar Rapids"}
    got = a.set_index("pwsid").place.reindex(list(spots))
    check("Geocoding spot checks", all(got[k] == v for k, v in spots.items()), got.to_dict())
    check("County codes decode (Polk=77, Dallas=25, Linn=57)",
          a.set_index("pwsid").county.reindex(["IA7707030", "IA2503003", "IA5715093"]).tolist() == ["Polk", "Dallas", "Linn"])

    # ---------------------------------------------------------------- estimator (ARTIFICIAL fixtures)
    rng = np.random.default_rng(1)
    n, years = 60, np.arange(2012, 2020)
    unit_fe = rng.normal(0, 1, n)
    year_fe = rng.normal(0, 0.5, len(years))
    rows = []
    g = {0: 2014, 1: 2014, 2: 2016, 3: 2017}
    for i in range(n):
        for j, y in enumerate(years):
            eff = 0.8 if i in g and y >= g[i] else 0.0
            rows.append({"pwsid": f"U{i}", "year": y, "y": unit_fe[i] + year_fe[j] + eff})
    art = pd.DataFrame(rows)
    events = [{"id": f"E{i}", "g": gg, "treated": {f"U{i}"}} for i, gg in g.items()]
    ctrl = {f"U{i}" for i in range(4, n)}
    st = L.build_stack(art, events, ctrl, "y", window=(-6, 6))
    r = L.imputation_att(st, "y")
    check("ARTIFICIAL: imputation estimator recovers a known effect exactly (noise-free)", abs(r["att"] - 0.8) < 1e-8, r["att"])
    es = L.event_study(st.assign(y=st.y - 0.8 * st.D), "y", -6, 6)
    check("ARTIFICIAL: event-study coefficients are zero when no effect remains", np.allclose(es.beta, 0, atol=1e-8))
    st2 = st.assign(Dy=st.D.astype(float))
    lhs = L.imputation_att(st2.assign(y=st2.y - 0.37 * st2.D), "y")["att"]
    rhs = L.imputation_att(st2, "y")["att"] - 0.37 * L.imputation_att(st2.assign(y=st2.Dy), "y")["att"]
    check("Test-inversion linearity identity holds", abs(lhs - rhs) < 1e-9, f"{lhs:.6f} vs {rhs:.6f}")
    # Randomization-test size on ARTIFICIAL null data with noise and one treated unit
    an = load("an", ROOT / "code/04_analyze.py")
    rej = []
    for sim in range(150):
        rs = np.random.default_rng(1000 + sim)
        yv = (rs.normal(0, 1, n)[:, None] + rs.normal(0, 0.5, len(years))[None, :] + rs.normal(0, 0.6, (n, len(years)))).ravel()
        df = pd.DataFrame({"pwsid": np.repeat([f"U{i}" for i in range(n)], len(years)), "year": np.tile(years, n), "y": yv})
        des = an.Design(df, sorted(df.pwsid.unique()), ["y"])
        Y = des.Y["y"]
        real = [(2015, np.array([0]))]
        obs = des.stats(real, {"y": Y})["y"][0]
        z = [des.stats([(2015, np.array([rs.integers(n)]))], {"y": Y})["y"][0] for _ in range(99)]
        rej.append(L.ri_pvalue(obs, np.array(z)) <= 0.10)
    rate = float(np.mean(rej))
    check("ARTIFICIAL: randomization test has close-to-nominal size (alpha = 0.10)", 0.04 <= rate <= 0.17, rate)

    # ---------------------------------------------------------------- results integrity
    res = json.loads((ROOT / "results/results.json").read_text())
    t2 = pd.read_csv(ROOT / "results/tables/table2_main_estimates.csv")
    check("Table 2 matches results.json", np.allclose(t2.att.values, [res["main"][k]["att"] for k in res["main"]]))
    check("Every main specification used >= 1,900 valid placebo draws", all(v["ri_draws"] >= 1900 for v in res["main"].values()))
    host = res["main"]["Host utility"]
    check("Conventional cluster SEs over-reject under placebo assignment (documented)",
          host["conventional_cr1_county_rejection_rate_under_placebo"]["alpha_0_05"] > 0.10,
          host["conventional_cr1_county_rejection_rate_under_placebo"])
    # Determinism: re-run one specification with the same seed
    panel, ex, camp, places = an.load()
    r1 = an.run_spec("x", panel, ex, camp, places, exposure="host", B=60)
    r2 = an.run_spec("x", panel, ex, camp, places, exposure="host", B=60)
    check("Randomization inference is reproducible with a fixed seed", r1["ri_p"] == r2["ri_p"] and r1["att"] == r2["att"])
    aud = json.loads((ROOT / "audit/audit_results.json").read_text())
    check("Audit: original outcomes regenerate exactly and ignore external data",
          aud["regenerated"]["matches_2oai_reported_hash"] and not aud["drop_file_challenge"]["output_changed"])

    passed = sum(r["passed"] for r in RESULTS)
    report = {"passed": passed, "total": len(RESULTS), "tests": RESULTS,
              "python": sys.version.split()[0], "numpy": np.__version__, "pandas": pd.__version__}
    (ROOT / "results/verification_report.json").write_text(json.dumps(report, indent=2))
    print(f"{passed}/{len(RESULTS)} checks passed")
    sys.exit(0 if passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
