"""Acquire observed public records. Never generates or imputes substitute observations.

Run from the package root:
    python code/00_extract_public_data.py            # SYR4 (2012-2019) + gazetteer
    python code/00_extract_public_data.py --syr3     # also try SYR3 (2006-2011)

Sources, in priority order
1. EPA Six-Year Review 4 (SYR4) national nitrate archive -> stream Iowa rows.
   The archive SHA-256 must match the audited release; a changed release stops.
2. If EPA is unreachable (e.g., a sandbox egress policy), retrieve the Iowa
   extract produced from that same archive by the 2-oai replication package,
   pinned to a git commit, and require its SHA-256 to match the value recorded
   in that package's acquisition log. Any mismatch stops the pipeline.
3. Optional SYR3 (2006-2011): EPA PhaseChem_3 archive (contains analyte 1040).
   Columns are normalised to SYR4 names and validated; if anything differs
   the script stops rather than guessing. SYR3 was NOT reachable from the
   environment in which the reported results were produced, so the reported
   analysis covers 2012-2019 only.
4. Iowa place coordinates: GeoNames 'cities500' table shipped inside the
   pinned PyPI package geonamescache==3.0.2 (no network needed).

Every attempt (success or failure) is written to data/raw/acquisition_log.json.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

SYR4_ZIP_URL = ("https://www.epa.gov/system/files/other-files/2024-03/"
                "_syr4_phasechem_4-hybrid-nitrate-to-nitrate.zip")
SYR4_MEMBER = "SUMMARY_ANALYTE_NITRATE.txt"
SYR4_ZIP_SHA256 = "5b8726c9adee8fbfa0ca265393814439d0f5d1a552b7a88b0322d19ec9d738e0"
SYR4_IOWA_SHA256 = "0aab0467dff6e70a5d0e87622c196eec12efb728a5a7593049ce093f689cbc19"
MIRROR_COMMIT = "68148b21e14a535dd37a63cda3fb9e1b63d5cc9c"
SYR4_IOWA_MIRROR = ("https://raw.githubusercontent.com/jsemprini/datacenter-nitrate-iowa/"
                    f"{MIRROR_COMMIT}/2-oai/data/raw/epa_syr4_iowa_nitrate_raw.csv")
SYR3_ZIP_URLS = [
    "https://www.epa.gov/sites/default/files/2016-12/syr3_phasechem_3.zip",
    "https://19january2025snapshot.epa.gov/sites/default/files/2016-12/syr3_phasechem_3.zip",
]
SYR4_COLUMNS = [
    "ANALYTE_CODE", "ANALYTE_NAME", "PRIMACY_CODE", "STATE_CODE", "PWSID", "SYSTEM_NAME",
    "SYSTEM_TYPE", "RETAIL_POPULATION_SERVED", "ADJUSTED_TOTAL_POPULATION_SERVED",
    "SOURCE_WATER_TYPE", "WATER_FACILITY_ID", "WATER_FACILITY_TYPE", "SAMPLING_POINT_ID",
    "SAMPLING_POINT_TYPE", "SOURCE_TYPE_CODE", "SAMPLE_TYPE_CODE", "LABORATORY_ASSIGNED_ID",
    "SIX_YEAR_ID", "SAMPLE_ID", "SAMPLE_COLLECTION_DATE", "DETECTION_LIMIT_VALUE",
    "DETECTION_LIMIT_UNIT", "DETECTION_LIMIT_CODE", "DETECT", "VALUE", "UNIT",
]
GEONAMES_PKG_VERSION = "3.0.2"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def download(url: str, path: Path, timeout: int = 120) -> dict:
    """Atomic download. Errors are recorded verbatim, never reinterpreted."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rec = {"url": url, "attempted_utc": now()}
    tmp = path.with_suffix(path.suffix + ".partial")
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "IowaNitrateResearch/2.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r, tmp.open("wb") as f:
            rec["http_status"] = r.status
            for block in iter(lambda: r.read(1 << 20), b""):
                f.write(block)
        tmp.replace(path)
        rec.update(ok=True, path=str(path), bytes=path.stat().st_size, sha256=sha256(path))
    except Exception as exc:  # noqa: BLE001 - we log every failure mode
        tmp.unlink(missing_ok=True)
        rec.update(ok=False, error=f"{type(exc).__name__}: {exc}")
    return rec


def normalise_columns(cols):
    out = []
    for c in cols:
        c = re.sub(r"[^A-Za-z0-9]+", "_", str(c).strip()).strip("_").upper()
        c = {"ANALYTE_ID": "ANALYTE_CODE", "VALUE_UNIT": "UNIT"}.get(c, c)
        out.append(c)
    return out


def iowa_nitrate_from_zip(archive: Path, member_hint: str | None) -> pd.DataFrame:
    """Stream tab-delimited members, keep Iowa analyte-1040 rows, all fields as text."""
    chunks = []
    with zipfile.ZipFile(archive) as z:
        members = [m for m in z.namelist() if m.lower().endswith(".txt")]
        if member_hint:
            members = [m for m in members if m == member_hint]
        if not members:
            raise SystemExit(f"No candidate text members in {archive}")
        for m in members:
            with z.open(m) as f:
                reader = pd.read_csv(f, sep="\t", encoding="cp1252", dtype=str, chunksize=200_000)
                for chunk in reader:
                    chunk.columns = normalise_columns(chunk.columns)
                    missing = set(SYR4_COLUMNS) - {"PRIMACY_CODE"} - set(chunk.columns)
                    if missing:
                        raise SystemExit(f"Schema mismatch in {m}: missing {sorted(missing)}")
                    keep = chunk["STATE_CODE"].eq("IA") & chunk["ANALYTE_CODE"].astype(str).str.strip().eq("1040")
                    if keep.any():
                        chunks.append(chunk.loc[keep])
    if not chunks:
        raise SystemExit("Archive contains no Iowa nitrate (1040) records")
    return pd.concat(chunks, ignore_index=True)


def acquire_syr4(raw: Path, cache: Path, log: list) -> None:
    out = raw / "epa_syr4_iowa_nitrate_raw.csv"
    if out.exists() and sha256(out) == SYR4_IOWA_SHA256:
        log.append({"step": "syr4_iowa", "status": "present_and_verified", "sha256": SYR4_IOWA_SHA256})
        return
    archive = cache / "syr4_nitrate.zip"
    rec = download(SYR4_ZIP_URL, archive) if not archive.exists() else {"url": SYR4_ZIP_URL, "ok": True, "cached": True}
    log.append({"step": "syr4_national_zip", **rec})
    if archive.exists():
        digest = sha256(archive)
        if digest != SYR4_ZIP_SHA256:
            raise SystemExit(f"SYR4 archive checksum changed ({digest}); review release before use")
        df = iowa_nitrate_from_zip(archive, SYR4_MEMBER)
        df.to_csv(out, index=False)
        log.append({"step": "syr4_iowa_from_epa", "rows": len(df), "sha256": sha256(out),
                    "matches_audited_extract": sha256(out) == SYR4_IOWA_SHA256})
        return
    # Fallback: pinned mirror of the same Iowa extract, hash-verified.
    rec = download(SYR4_IOWA_MIRROR, out)
    rec["step"] = "syr4_iowa_from_pinned_mirror"
    if rec.get("ok"):
        rec["matches_audited_extract"] = rec["sha256"] == SYR4_IOWA_SHA256
    log.append(rec)
    if not rec.get("ok") or rec["sha256"] != SYR4_IOWA_SHA256:
        out.unlink(missing_ok=True)
        raise SystemExit("Could not obtain a verified SYR4 Iowa extract; no data substituted")


def acquire_syr3(raw: Path, cache: Path, log: list) -> None:
    archive = cache / "syr3_phasechem_3.zip"
    for url in SYR3_ZIP_URLS:
        if archive.exists():
            break
        rec = download(url, archive, timeout=300)
        rec["step"] = "syr3_phasechem_3_zip"
        log.append(rec)
    if not archive.exists():
        log.append({"step": "syr3", "status": "not_acquired",
                    "consequence": "analysis restricted to SYR4 (2012-2019)"})
        return
    df = iowa_nitrate_from_zip(archive, None)
    df = df.reindex(columns=[c for c in SYR4_COLUMNS if c in df.columns])
    out = raw / "epa_syr3_iowa_nitrate_raw.csv"
    df.to_csv(out, index=False)
    log.append({"step": "syr3_iowa", "rows": len(df), "pws": df.PWSID.nunique(),
                "archive_sha256": sha256(archive), "sha256": sha256(out)})


def acquire_places(raw: Path, log: list) -> None:
    import geonamescache  # pinned in requirements.txt
    from importlib.metadata import version
    v = version("geonamescache")
    if v != GEONAMES_PKG_VERSION:
        raise SystemExit(f"geonamescache {v} installed; {GEONAMES_PKG_VERSION} required for reproducibility")
    gc = geonamescache.GeonamesCache(min_city_population=500)
    rows = [{"geonameid": c["geonameid"], "place": c["name"], "lat": c["latitude"],
             "lon": c["longitude"], "population_geonames": c["population"]}
            for c in gc.get_cities().values() if c["countrycode"] == "US" and c["admin1code"] == "IA"]
    df = pd.DataFrame(rows).sort_values(["place", "geonameid"])
    out = raw / "geonames_iowa_places.csv"
    df.to_csv(out, index=False)
    log.append({"step": "iowa_places", "source": f"GeoNames cities500 via geonamescache=={v}",
                "rows": len(df), "sha256": sha256(out)})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=".")
    ap.add_argument("--syr3", action="store_true", help="also try EPA SYR3 2006-2011")
    args = ap.parse_args()
    root = Path(args.root)
    raw, cache = root / "data/raw", root / "cache"
    raw.mkdir(parents=True, exist_ok=True)
    cache.mkdir(exist_ok=True)
    log: list = [{"run_started_utc": now()}]
    try:
        acquire_syr4(raw, cache, log)
        if args.syr3:
            acquire_syr3(raw, cache, log)
        acquire_places(raw, log)
    finally:
        (raw / "acquisition_log.json").write_text(json.dumps(log, indent=2))
    print(json.dumps(log, indent=2))


if __name__ == "__main__":
    main()
