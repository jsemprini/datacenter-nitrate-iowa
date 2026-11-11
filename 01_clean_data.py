"""Clean EPA compliance nitrate records and build PWS attributes and an annual panel.

Input : data/raw/epa_syr4_iowa_nitrate_raw.csv (and epa_syr3_... if acquired)
        data/raw/geonames_iowa_places.csv
Output: data/clean/nitrate_samples_clean.csv   one row per analytical result
        data/clean/pws_attributes.csv          one row per community water system
        data/clean/nitrate_annual_panel.csv    one row per PWS-year with >=1 eligible sample
        data/clean/cleaning_summary.json

Key rules (all documented in the manuscript):
* Analyte 1040 is regulatory nitrate reported as N. Result and detection-limit units
  are converted independently (ug/L -> mg/L divide by 1000).
* Non-detects keep the interval [0, reporting limit]; a midpoint convention
  (limit / sqrt 2) is used for the primary series and the bounds for sensitivity.
* Water stage: explicit raw (SOURCE_TYPE_CODE RW, sampling point RW/SR, or a
  well/intake/gallery/spring/reservoir facility with no source code) is RAW; the
  remaining ROUTINE compliance records are ENTRY (40 CFR 141.23(a): inorganic
  compliance samples are taken at each entry point to the distribution system).
  Process-control (PC) points are excluded. Raw samples are never averaged with
  entry samples.
* Missing years stay missing; nothing is interpolated or filled.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

IOWA_COUNTIES = [
    "Adair", "Adams", "Allamakee", "Appanoose", "Audubon", "Benton", "Black Hawk", "Boone",
    "Bremer", "Buchanan", "Buena Vista", "Butler", "Calhoun", "Carroll", "Cass", "Cedar",
    "Cerro Gordo", "Cherokee", "Chickasaw", "Clarke", "Clay", "Clayton", "Clinton", "Crawford",
    "Dallas", "Davis", "Decatur", "Delaware", "Des Moines", "Dickinson", "Dubuque", "Emmet",
    "Fayette", "Floyd", "Franklin", "Fremont", "Greene", "Grundy", "Guthrie", "Hamilton",
    "Hancock", "Hardin", "Harrison", "Henry", "Howard", "Humboldt", "Ida", "Iowa", "Jackson",
    "Jasper", "Jefferson", "Johnson", "Jones", "Keokuk", "Kossuth", "Lee", "Linn", "Louisa",
    "Lucas", "Lyon", "Madison", "Mahaska", "Marion", "Marshall", "Mills", "Mitchell", "Monona",
    "Monroe", "Montgomery", "Muscatine", "O'Brien", "Osceola", "Page", "Palo Alto", "Plymouth",
    "Pocahontas", "Polk", "Pottawattamie", "Poweshiek", "Ringgold", "Sac", "Scott", "Shelby",
    "Sioux", "Story", "Tama", "Taylor", "Union", "Van Buren", "Wapello", "Warren", "Washington",
    "Wayne", "Webster", "Winnebago", "Winneshiek", "Woodbury", "Worth", "Wright",
]
assert len(IOWA_COUNTIES) == 99

UTILITY_WORDS = {
    "WATER", "WTR", "SUPPLY", "SUPPLIES", "SPLY", "WORKS", "WRKS", "DEPARTMENT", "DEPT", "DEP",
    "MUNICIPAL", "MUNIC", "MUNI", "MUN", "UTILITIES", "UTILITY", "UTIL", "UTILS", "SYSTEM", "SYS",
    "CITY", "OF", "PWS", "THE", "PLANT", "TREATMENT", "TRMT", "BOARD", "TRUSTEES", "COMMISSION",
    "LIGHT", "POWER", "AND", "IA", "IOWA", "WS", "WW", "CO", "COMPANY", "DIVISION", "DIV",
    "DISTRICT", "DIST", "WATERWORKS", "MUNICIPALITY", "TOWN", "MU", "MUNIC.",
}
NON_MUNICIPAL = re.compile(
    r"\b(RURAL|RWA|RWS|RWD|REGIONAL|ASSN|ASSOC|ASSOCIATION|MOBILE|MHP|MHC|COURT|CAMP|ESTATES|"
    r"SUBDIV|SUBDIVISION|ADDITION|HOA|COOP|CO-OP|CORRECTIONAL|PRISON|UNIVERSITY|COLLEGE|"
    r"SCHOOL|HOSPITAL|NURSING|CARE|MANOR|VILLAGE|ACRES|HEIGHTS|HILLS|SHORES|BEACH|RESORT|"
    r"CLUB|CORP|INC|LLC|PROPERTY|OWNERS|TRAILER|APARTMENTS|APTS|TERRACE|DEVELOPMENT|"
    r"COMMUNITY|FARM|FARMS|STATE PARK|MEADOWS|RIDGE|POINT|WOODS)\b")
ABBREV = {"ST": "SAINT", "MT": "MOUNT", "FT": "FORT", "N": "NORTH", "S": "SOUTH",
          "E": "EAST", "W": "WEST", "PT": "POINT", "LK": "LAKE", "JCT": "JUNCTION"}
NAME_ALIASES = {"LEMARS": "LE MARS"}


def unit_factor(u: str) -> float:
    return {"UG/L": 0.001, "MG/L": 1.0}.get(str(u).strip().upper(), np.nan)


def classify_stage(row) -> str:
    src = str(row.SOURCE_TYPE_CODE or "").upper()
    pt = str(row.SAMPLING_POINT_TYPE or "").upper()
    fac = str(row.WATER_FACILITY_TYPE or "").upper()
    if pt in {"PC", "UP"}:
        return "process_control"
    raw = src == "RW" or pt in {"RW", "SR"} or (src in {"", "NAN"} and fac in {"IG", "IN", "RS", "SP", "WL", "WH", "CC"})
    fin = src == "FN" or pt in {"EP", "FN", "DS", "FC"}
    if raw and fin:
        return "conflict"
    return "raw" if raw else "entry"


def norm_tokens(name: str) -> list[str]:
    s = re.sub(r"[^A-Z0-9 ]+", " ", str(name).upper().replace("'", ""))
    s = " ".join(NAME_ALIASES.get(t, t) for t in s.split())
    return [ABBREV.get(t, t) for t in s.split()]


def build_place_lookup(places: pd.DataFrame) -> dict:
    lut: dict[str, list[dict]] = {}
    for r in places.itertuples():
        key = " ".join(norm_tokens(r.place))
        lut.setdefault(key, []).append({"place": r.place, "lat": r.lat, "lon": r.lon,
                                        "population_geonames": r.population_geonames})
    return lut


def geocode(name: str, lut: dict) -> tuple[list[dict], str]:
    """Return candidate places and the matching rule; ambiguity is resolved later by county."""
    up = str(name).upper()
    if NON_MUNICIPAL.search(up):
        return [], "non_municipal_name"
    toks = norm_tokens(name)
    core = [t for t in toks if t not in UTILITY_WORDS]
    key = " ".join(core)
    if key in lut:
        return lut[key], "exact"
    # n-gram fallback (e.g. 'IOWA-AMERICAN WTR CO-DAVENPORT'), longest first
    for n in range(len(toks), 0, -1):
        hits = {" ".join(toks[i:i + n]) for i in range(len(toks) - n + 1)} & set(lut)
        hits = {h for h in hits if h not in {"WATER", "IOWA", "CITY"}}
        if len(hits) == 1:
            return lut[hits.pop()], "ngram"
        if len(hits) > 1:
            return [], "ambiguous"
    return [], "no_match"


def load_raw(root: Path) -> pd.DataFrame:
    frames = []
    for name, release in [("epa_syr3_iowa_nitrate_raw.csv", "SYR3"), ("epa_syr4_iowa_nitrate_raw.csv", "SYR4")]:
        p = root / "data/raw" / name
        if p.exists():
            d = pd.read_csv(p, dtype=str, keep_default_na=False, na_values=[""])
            d["release"] = release
            frames.append(d)
    if not frames:
        raise SystemExit("No raw EPA extract found; run code/00_extract_public_data.py")
    return pd.concat(frames, ignore_index=True)


def parse_dates(s: pd.Series) -> pd.Series:
    out = pd.to_datetime(s, format="%d-%b-%y", errors="coerce")
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%d-%b-%Y", "%m/%d/%Y %H:%M:%S"):
        miss = out.isna()
        if not miss.any():
            break
        out[miss] = pd.to_datetime(s[miss], format=fmt, errors="coerce")
    if out.isna().any():
        raise SystemExit(f"{int(out.isna().sum())} unparseable collection dates")
    return out


def clean_samples(raw: pd.DataFrame) -> pd.DataFrame:
    x = raw.copy()
    if not x.ANALYTE_CODE.astype(str).str.strip().eq("1040").all():
        raise SystemExit("Non-nitrate analyte present")
    n0 = len(x)
    x = x.drop_duplicates(subset=[c for c in x.columns if c != "release"])
    if x.SIX_YEAR_ID.duplicated().any() and x.release.nunique() == 1:
        raise SystemExit("Conflicting duplicate SIX_YEAR_ID within a release")
    x["n_exact_duplicates_dropped"] = n0 - len(x)
    x["pwsid"] = x.PWSID.str.upper().str.strip()
    x["date"] = parse_dates(x.SAMPLE_COLLECTION_DATE)
    x["year"] = x.date.dt.year
    x["quarter"] = x.date.dt.quarter
    x["stage"] = [classify_stage(r) for r in x[["SOURCE_TYPE_CODE", "SAMPLING_POINT_TYPE", "WATER_FACILITY_TYPE"]].fillna("").itertuples()]
    val = pd.to_numeric(x.VALUE, errors="coerce") * x.UNIT.map(unit_factor)
    lim = pd.to_numeric(x.DETECTION_LIMIT_VALUE, errors="coerce") * x.DETECTION_LIMIT_UNIT.map(unit_factor)
    det = x.DETECT.astype(str).eq("1")
    nd = x.DETECT.astype(str).eq("0")
    ok_det = det & val.ge(0)
    ok_nd = nd & lim.gt(0)
    x["censored"] = nd
    x["nitrate_lower"] = np.where(ok_det, val, np.where(ok_nd, 0.0, np.nan))
    x["nitrate_upper"] = np.where(ok_det, val, np.where(ok_nd, lim, np.nan))
    x["nitrate_mid"] = np.where(ok_det, val, np.where(ok_nd, lim / np.sqrt(2), np.nan))
    x["limit_mg_l"] = lim
    x["eligible"] = (x.SYSTEM_TYPE.eq("C") & x.SAMPLE_TYPE_CODE.eq("RT") & x.nitrate_mid.notna()
                     & x.stage.isin(["entry", "raw"]))
    x["data_class"] = "observed_epa_" + x.release.str.lower()
    keep = ["SIX_YEAR_ID", "release", "pwsid", "SYSTEM_NAME", "SYSTEM_TYPE", "SOURCE_WATER_TYPE",
            "ADJUSTED_TOTAL_POPULATION_SERVED", "WATER_FACILITY_ID", "WATER_FACILITY_TYPE",
            "SAMPLING_POINT_ID", "SAMPLING_POINT_TYPE", "SOURCE_TYPE_CODE", "SAMPLE_TYPE_CODE",
            "date", "year", "quarter", "stage", "VALUE", "UNIT", "DETECT", "DETECTION_LIMIT_VALUE",
            "DETECTION_LIMIT_UNIT", "censored", "limit_mg_l", "nitrate_lower", "nitrate_mid",
            "nitrate_upper", "eligible", "data_class"]
    return x[keep]


def pws_attributes(x: pd.DataFrame, places: pd.DataFrame) -> pd.DataFrame:
    c = x.loc[x.SYSTEM_TYPE.eq("C")].copy()
    c["pop"] = pd.to_numeric(c.ADJUSTED_TOTAL_POPULATION_SERVED, errors="coerce")
    g = c.groupby("pwsid")
    a = pd.DataFrame({
        "system_name": g.SYSTEM_NAME.agg(lambda s: s.mode().iat[0]),
        "source_water_type": g.SOURCE_WATER_TYPE.agg(lambda s: s.mode().iat[0]),
        "population_served": g["pop"].max(),
        "n_samples_all": g.size(),
    }).reset_index()
    a["county_code"] = a.pwsid.str[2:4]
    a["county"] = [IOWA_COUNTIES[int(cc) - 1] if cc.isdigit() and 1 <= int(cc) <= 99 else None
                   for cc in a.county_code]
    lut = build_place_lookup(places)
    geo = [geocode(n, lut) for n in a.system_name]
    a["geocode_method"] = [m for _, m in geo]
    first = [c[0] if len(c) == 1 else None for c, _ in geo]
    a["place"] = [g_["place"] if g_ else None for g_ in first]
    a["lat"] = [g_["lat"] if g_ else np.nan for g_ in first]
    a["lon"] = [g_["lon"] if g_ else np.nan for g_ in first]
    # Same-name places: choose the candidate nearest the county median of unique matches.
    med = a.dropna(subset=["lat"]).groupby("county")[["lat", "lon"]].median()
    for i, (cands, _) in enumerate(geo):
        if len(cands) > 1 and a.at[i, "county"] in med.index:
            m = med.loc[a.at[i, "county"]]
            d = [float(haversine(c["lat"], c["lon"], m.lat, m.lon)) for c in cands]
            best = cands[int(np.argmin(d))]
            a.loc[i, ["place", "lat", "lon"]] = [best["place"], best["lat"], best["lon"]]
            a.at[i, "geocode_method"] += "_county_disambiguated"
    # QA: a geocoded place must lie near the other geocoded places of the PWSID county.
    med = a.dropna(subset=["lat"]).groupby("county")[["lat", "lon"]].median()
    a = a.join(med, on="county", rsuffix="_county_median")
    dkm = haversine(a.lat, a.lon, a.lat_county_median, a.lon_county_median)
    a["county_check_km"] = dkm
    bad = dkm > 60
    a.loc[bad, "geocode_method"] = "rejected_county_mismatch"
    a.loc[bad, ["place", "lat", "lon"]] = [None, np.nan, np.nan]
    a = a.drop(columns=["lat_county_median", "lon_county_median"])
    # Approximate 3x3 regions mirroring Iowa's NOAA climate-division layout (used for region-by-year controls)
    lat_cut, lon_cut = [41.42, 42.46], [-94.47, -92.31]
    a["region"] = [(f"R{1 + int(np.digitize(la, lat_cut))}{1 + int(np.digitize(lo, lon_cut))}"
                    if np.isfinite(la) else None) for la, lo in zip(a.lat, a.lon)]
    return a


def haversine(lat1, lon1, lat2, lon2):
    lat1, lon1, lat2, lon2 = (np.radians(np.asarray(v, dtype=float)) for v in (lat1, lon1, lat2, lon2))
    h = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(h))


def annual_panel(x: pd.DataFrame) -> pd.DataFrame:
    """Sample -> point-year mean -> equal-weight mean over points within PWS-year-stage."""
    e = x.loc[x.eligible].copy()
    e["point"] = e.SAMPLING_POINT_ID.fillna("UNKNOWN")
    keys = ["pwsid", "stage", "year"]
    pt = (e.groupby(keys + ["point"]).agg(
        mid=("nitrate_mid", "mean"), lo=("nitrate_lower", "mean"), hi=("nitrate_upper", "mean"),
        mx=("nitrate_upper", "max"), mx_lo=("nitrate_lower", "max"), n=("SIX_YEAR_ID", "size"),
        nq=("quarter", "nunique"), det=("censored", lambda s: 1 - s.mean())).reset_index())
    p = (pt.groupby(keys).agg(
        nitrate_mean=("mid", "mean"), nitrate_mean_lower=("lo", "mean"), nitrate_mean_upper=("hi", "mean"),
        nitrate_max_upper=("mx", "max"), nitrate_max_lower=("mx_lo", "max"), n_samples=("n", "sum"),
        n_points=("point", "size"), n_quarters_max=("nq", "max"), detect_share=("det", "mean"))
        .reset_index())
    p["exceed5_lower"] = (p.nitrate_max_lower > 5).astype(int)
    p["exceed5_upper"] = (p.nitrate_max_upper > 5).astype(int)
    p["log_nitrate"] = np.log(p.nitrate_mean.clip(lower=0.01))
    return p


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    root = Path(ap.parse_args().root)
    out = root / "data/clean"
    out.mkdir(parents=True, exist_ok=True)
    raw = load_raw(root)
    places = pd.read_csv(root / "data/raw/geonames_iowa_places.csv")
    x = clean_samples(raw)
    x.to_csv(out / "nitrate_samples_clean.csv", index=False)
    attrs = pws_attributes(x, places)
    attrs.to_csv(out / "pws_attributes.csv", index=False)
    panel = annual_panel(x)
    panel.to_csv(out / "nitrate_annual_panel.csv", index=False)
    c = x.loc[x.SYSTEM_TYPE.eq("C")]
    summary = {
        "releases": sorted(x.release.unique().tolist()),
        "date_range": [str(x.date.min().date()), str(x.date.max().date())],
        "raw_rows": int(len(raw)), "rows_after_exact_dedup": int(len(x)),
        "all_pws": int(x.pwsid.nunique()), "community_rows": int(len(c)),
        "community_pws": int(c.pwsid.nunique()),
        "community_stage_counts": c.stage.value_counts().to_dict(),
        "community_sample_type_counts": c.SAMPLE_TYPE_CODE.value_counts().to_dict(),
        "eligible_rows": int(x.eligible.sum()), "eligible_pws": int(x.loc[x.eligible, "pwsid"].nunique()),
        "eligible_entry_rows": int((x.eligible & x.stage.eq("entry")).sum()),
        "eligible_raw_rows": int((x.eligible & x.stage.eq("raw")).sum()),
        "censored_share_eligible": float(x.loc[x.eligible, "censored"].mean()),
        "unusable_numeric_rows": int(x.nitrate_mid.isna().sum()),
        "source_water_type_pws": attrs.source_water_type.value_counts().to_dict(),
        "geocode_methods": attrs.geocode_method.value_counts().to_dict(),
        "geocoded_pws": int(attrs.lat.notna().sum()),
        "panel_rows_entry": int(panel.stage.eq("entry").sum()),
        "panel_rows_raw": int(panel.stage.eq("raw").sum()),
        "panel_pws_entry": int(panel.loc[panel.stage.eq("entry"), "pwsid"].nunique()),
    }
    (out / "cleaning_summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))


if __name__ == "__main__":
    main()
