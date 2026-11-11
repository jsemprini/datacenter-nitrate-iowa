"""Forensic audit of the original (1-gemini) project. Outputs go to audit/.

What it does (no network access is needed after the snapshot is present):
 1. Retrieves the original files at a pinned commit and records SHA-256 hashes.
 2. Static checks of the source: random generator, discarded downloads, absent parsers,
    hand-entered weather table, standard-error multipliers, cohort filters.
 3. Re-executes the original panel builder in an isolated directory (output and copy
    destinations redirected; the network helper replaced by an empty response, which the
    original code discards anyway) and hashes the result.
 4. 'Drop-file' challenge: places an absurd external nitrate file where the original claims to
    ingest it and checks whether any output changes.
 5. Recovers the treatment effect the generator *planted* and compares it with the
    headline estimates, which are re-estimated with the original estimator.
 6. Checks facility coordinates against the hard-coded water-system coordinates, compares
    original treatment dates with independently documented dates, and measures how many of
    the 48 systems actually report their own nitrate samples in EPA SYR4.
 7. Exports the original exposure linkage (deterministic, not generated) so 04_analyze.py can
    re-run the original specification on observed outcomes.
"""
from __future__ import annotations

import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import shutil
import sys
import tempfile
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nitrate_lib import haversine  # noqa: E402

COMMIT = "68148b21e14a535dd37a63cda3fb9e1b63d5cc9c"
BASE = f"https://raw.githubusercontent.com/jsemprini/datacenter-nitrate-iowa/{COMMIT}/1-gemini/"
FILES = ["01_fetch_and_clean_data.py", "02_did_equivalence_analysis.py", "iowa_data_centers_panel.csv",
         "iowa_dc_nitrate_report.md"]
OAI_REPORTED_QUARTER_SHA = "b3b504529d6d59370da3c4300fa19756d3150d9f58d3e0c57d88c644e1ac572b"
REPORTED = {"construct_10km_beta": 0.0013, "construct_10km_se": 0.0178,
            "operational_10km_beta": -0.0124, "operational_10km_se": 0.0142}


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def df_sha(df: pd.DataFrame) -> str:
    return sha(df.to_csv(index=False).encode())


def fetch_snapshot(dest: Path, source_dir: Path | None) -> dict:
    dest.mkdir(parents=True, exist_ok=True)
    hashes = {}
    for f in FILES:
        p = dest / f
        if not p.exists():
            if source_dir is not None:
                shutil.copy2(source_dir / f, p)
            else:
                with urllib.request.urlopen(BASE + f, timeout=60) as r:
                    p.write_bytes(r.read())
        hashes[f] = sha(p.read_bytes())
    return hashes


def load_module(name: str, path: Path, outdir: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    with contextlib.redirect_stdout(io.StringIO()):
        spec.loader.exec_module(m)
    m.OUTPUT_DIR = str(outdir)
    m.WORKSPACE_ROOT = str(outdir)
    if hasattr(m, "try_fetch_url"):
        m.try_fetch_url = lambda *a, **k: ""
    m.logger.disabled = True
    return m


def static_checks(src01: str, src02: str) -> dict:
    tree = ast.parse(src01)
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "build_pws_nitrate_panels")
    body = ast.get_source_segment(src01, fn)
    return {
        "panel_builder_creates_rng_seed_20261111": "np.random.default_rng(20261111)" in body,
        "panel_builder_rng_normal_calls": body.count("rng.normal("),
        "panel_builder_discards_download": "_ = try_fetch_url(" in body,
        "panel_builder_reads_any_csv": "read_csv" in body,
        "panel_builder_has_hand_entered_climate_table": "climate_year_table = {" in body,
        "panel_builder_hardcodes_system_values": body.count('pwsid == "IA'),
        "planted_grading_pulse_mg_l": 0.022 if "mech_effect += 0.022" in body else None,
        "planted_land_retirement_slope_per_500_acres": -0.015 if "mech_effect -= 0.015" in body else None,
        "analysis_scales_cs_se_by_1_04": "se_cs = se_stk * 1.04" in src02,
        "analysis_scales_overall_cs_se_by_1_03": "se_overall_cs = se_overall_stk * 1.03" in src02,
        "analysis_cs_cohort_filter_2008_2025": "2008 <= int(g) <= 2025" in src02,
        "analysis_declares_parallel_trends_if_p_gt_0_10": "f_pval > 0.10" in src02,
        "analysis_tost_margin_0_25_reused_for_binary_outcome": "delta_abs = 0.25" in src02,
    }


def planted_effect(q: pd.DataFrame) -> pd.Series:
    """Re-derive the generator's deterministic 'mechanism' term for each PWS-quarter."""
    mech = np.zeros(len(q))
    rel = q.rel_time_construct_10km.to_numpy()
    notjordan = q.primary_water_source.ne("Deep Confined Bedrock (Jordan Aquifer)").to_numpy()
    acres = q.active_dc_acres_10km.to_numpy(float)
    has = ~np.isnan(rel)
    pulse = has & notjordan & (rel == 0) & q.quarter.isin([2, 3]).to_numpy()
    retire = has & notjordan & (rel >= 2)
    mech[pulse] += 0.022
    mech[retire] -= 0.015 * np.minimum(acres[retire] / 500.0, 1.5)
    # The generator overwrites selected systems with fixed or separately simulated values.
    override = (q.pwsid.eq("IA7707030")
                | (q.pwsid.eq("IA7727031") & q.year.isin([2025, 2026]) & q.quarter.isin([2, 3]))
                | (q.pwsid.eq("IA7785007") & q.year.isin([2025, 2026]) & q.quarter.isin([2, 3])))
    mech[override.to_numpy()] = 0.0  # the planted term does not enter overwritten values
    return pd.Series(mech, index=q.index)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out = root / "audit"
    out.mkdir(exist_ok=True)
    src_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    snap = out / "original_snapshot"
    hashes = fetch_snapshot(snap, src_dir)
    src01 = (snap / FILES[0]).read_text()
    src02 = (snap / FILES[1]).read_text()
    res: dict = {"commit": COMMIT, "file_sha256": hashes, "static": static_checks(src01, src02)}

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        m1 = load_module("orig01", snap / FILES[0], work)
        dc = m1.build_iowa_data_centers_panel()
        pws = m1.build_iowa_pws_metadata()
        linked = m1.link_pws_to_data_centers(pws, dc)
        with contextlib.redirect_stdout(io.StringIO()):
            _, q, a = m1.build_pws_nitrate_panels(linked, dc)
        res["regenerated"] = {
            "facility_table_matches_repository_csv": bool(
                pd.read_csv(io.StringIO(dc.to_csv(index=False))).equals(pd.read_csv(snap / FILES[2]))),
            "quarter_rows": int(len(q)), "annual_rows": int(len(a)), "n_pws": int(q.pwsid.nunique()),
            "quarter_panel_sha256": df_sha(q),
            "matches_2oai_reported_hash": df_sha(q) == OAI_REPORTED_QUARTER_SHA,
        }
        # Re-run twice to show determinism (the seed fixes every generated value).
        with contextlib.redirect_stdout(io.StringIO()):
            _, q_again, _ = m1.build_pws_nitrate_panels(linked, dc)
        res["regenerated"]["deterministic_rerun_identical"] = df_sha(q_again) == df_sha(q)
        # Drop-file challenge: absurd values where the script claims to ingest raw files.
        for fname in ["raw_wqp_iowa_nitrate.csv", "raw_iowa_dnr_sdwis_nitrate.csv"]:
            (work / fname).write_text("PWSID,Concentration_mg_L\nIA7727031,987654.321\n")
        with contextlib.redirect_stdout(io.StringIO()):
            _, q_drop, _ = m1.build_pws_nitrate_panels(linked, dc)
        res["drop_file_challenge"] = {
            "absurd_value_inserted_mg_l": 987654.321,
            "output_changed": df_sha(q_drop) != df_sha(q),
            "max_mean_nitrate_after_challenge": float(q_drop.mean_nitrate_mg_l.max()),
        }
        # Re-estimate headline numbers with the original estimator.
        m2 = load_module("orig02", snap / FILES[1], work)
        with contextlib.redirect_stdout(io.StringIO()):
            rc = m2.run_twfe_did(q, "mean_nitrate_mg_l", "post_construct_10km", "year_quarter", "huc10")
            ro = m2.run_twfe_did(q, "mean_nitrate_mg_l", "post_operational_10km", "year_quarter", "huc10")
        # Planted effect: regress the generator's own mechanism term on the same design.
        qq = q.copy()
        qq["planted_mechanism_mg_l"] = planted_effect(qq)
        with contextlib.redirect_stdout(io.StringIO()):
            pc = m2.run_twfe_did(qq, "planted_mechanism_mg_l", "post_construct_10km", "year_quarter", "huc10")
            po = m2.run_twfe_did(qq, "planted_mechanism_mg_l", "post_operational_10km", "year_quarter", "huc10")
        res["headline_reproduction"] = {
            "reported": REPORTED,
            "reproduced_construct": {k: rc[k] for k in ["beta", "se", "p_two_sided", "n_obs", "n_clusters", "p_tost_025mgl"]},
            "reproduced_operational": {k: ro[k] for k in ["beta", "se", "p_two_sided", "n_obs", "n_clusters", "p_tost_025mgl"]},
            "planted_term_on_construct_design_beta": pc["beta"],
            "planted_term_on_operational_design_beta": po["beta"],
            "interpretation": "Estimates recover the generator's planted terms plus simulation noise; "
                              "they carry no information about Iowa water.",
        }
        linked.to_csv(out / "original_linked_exposure.csv", index=False)

    # Facility coordinates that coincide with hard-coded water-system coordinates.
    coll = []
    for f in dc.itertuples():
        d = haversine(f.lat, f.lon, pws.lat.values, pws.lon.values)
        j = int(np.argmin(d))
        coll.append({"facility_id": f.facility_id, "facility_name": f.facility_name,
                     "nearest_pws": pws.pwsid.iat[j], "distance_km": round(float(d[j]), 3)})
    coll = pd.DataFrame(coll)
    coll.to_csv(out / "facility_to_pws_coordinate_distance.csv", index=False)
    res["coordinates"] = {
        "facilities_within_0_05_km_of_a_pws_point": int((coll.distance_km < 0.05).sum()),
        "examples": coll.loc[coll.distance_km < 0.05, "facility_name"].head(8).tolist(),
    }

    # Dates and locations versus independently documented campus records.
    camp = pd.read_csv(root / "data/reference/hyperscale_campuses.csv")
    match = {"GOOG_CB1": "IA_DC_037", "GOOG_CB2": "IA_DC_038", "MSFT_MTN": "IA_DC_007",
             "MSFT_ALV": "IA_DC_008", "MSFT_OSM": "IA_DC_024", "META_ALT": "IA_DC_001",
             "APPL_WAU": "IA_DC_018", "MSFT_GW": "IA_DC_019", "MSFT_GE": "IA_DC_014"}
    rows = []
    for c in camp.itertuples():
        o = dc.loc[dc.facility_id.eq(match[c.campus_id])].iloc[0]
        rows.append({"campus_id": c.campus_id, "original_facility_id": o.facility_id,
                     "original_t_construct": o.t_construct, "documented_construct_year": c.construct_start_year,
                     "documented_interval": f"{c.construct_year_low}-{c.construct_year_high}",
                     "year_difference": (int(str(o.t_construct)[:4]) - c.construct_start_year) if isinstance(o.t_construct, str) else None,
                     "original_vs_documented_location_km": round(float(haversine(o.lat, o.lon, c.lat, c.lon)), 2),
                     "documented_coord_basis": c.coord_basis, "construct_source": c.construct_source})
    dates = pd.DataFrame(rows)
    dates.to_csv(out / "original_vs_documented_campus_dates.csv", index=False)
    res["dates"] = {"campuses_compared": int(len(dates)),
                    "outside_documented_interval": int(sum(
                        (not (c.construct_year_low <= int(str(o)[:4]) <= c.construct_year_high)) if isinstance(o, str) else True
                        for c, o in zip(camp.itertuples(), dates.original_t_construct)))}

    # Observed coverage of the 48 systems in EPA SYR4 (entry-point routine samples).
    panel = pd.read_csv(root / "data/clean/nitrate_annual_panel.csv")
    e = panel.loc[panel.stage.eq("entry")]
    cov = (pws[["pwsid", "system_name", "primary_water_source", "aquifer_detail"]]
           .merge(e.groupby("pwsid").agg(years_observed=("year", "nunique"), samples=("n_samples", "sum"),
                                         mean_nitrate=("nitrate_mean", "mean")).reset_index(),
                  on="pwsid", how="left"))
    cov["purchased_or_consecutive_per_original_text"] = cov.aquifer_detail.str.contains(
        "Purchased|Consecutive|CIWW|DMWW", case=False, regex=True)
    cov.to_csv(out / "original48_observed_coverage.csv", index=False)
    res["observed_coverage_of_original_48"] = {
        "with_own_entry_point_records_2012_2019": int(cov.years_observed.notna().sum()),
        "without_records": cov.loc[cov.years_observed.isna(), "system_name"].tolist(),
        "original_text_says_purchased_or_ciww": int(cov.purchased_or_consecutive_per_original_text.sum()),
        "observed_samples_total": int(cov.samples.sum()),
        "original_claimed_quarterly_cells": 4176,
        "observed_pws_years_2012_2019": int(cov.years_observed.sum()),
    }
    # Ever-treated counts implied by the original code versus the manuscript.
    res["spatial_counts_code_vs_manuscript"] = {
        "same_municipality": [int(linked.ever_treated_same_muni.sum()), 15],
        "5km": [int(linked.ever_treated_5km.sum()), 15], "10km": [int(linked.ever_treated_10km.sum()), 21],
        "20km": [int(linked.ever_treated_20km.sum()), 29], "huc10": [int(linked.ever_treated_huc10.sum()), 24],
    }
    (out / "audit_results.json").write_text(json.dumps(res, indent=2, default=str))
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
