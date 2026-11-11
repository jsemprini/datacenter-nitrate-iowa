"""Assign data-center exposure to community water systems from documented campus records.

Exposure definitions (all are 'first construction start' events, by calendar year):
  host       : the utility that supplies the campus (documented for Microsoft/WDMWW; presumed
               municipal utility of the host city otherwise).
  radius R   : a geocoded municipal system whose place centroid is within R km of the campus
               (R = 5, 10, 15, 20, 30). Exploratory proximity screen; it does not establish a
               hydrologic connection.
Controls are systems farther than 30 km from every documented campus (tier A or B). A
stricter screen also drops systems within 10 km of any site in the unverified 70-row
original facility table.

Outputs: data/clean/pws_campus_distance.csv, data/clean/exposure.csv
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from nitrate_lib import haversine  # noqa: E402

RADII = [5, 10, 15, 20, 30]
CONTROL_BUFFER_KM = 30


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    attrs = pd.read_csv(root / "data/clean/pws_attributes.csv")
    camp = pd.read_csv(root / "data/reference/hyperscale_campuses.csv")
    orig = pd.read_csv(root / "data/reference/original_1gemini_facilities_UNVERIFIED.csv")
    g = attrs.dropna(subset=["lat"]).copy()

    dist = []
    for r in g.itertuples():
        d = haversine(r.lat, r.lon, camp.lat.values, camp.lon.values)
        for cid, dk in zip(camp.campus_id, d):
            dist.append({"pwsid": r.pwsid, "campus_id": cid, "distance_km": float(dk)})
    dist = pd.DataFrame(dist)
    dist.to_csv(root / "data/clean/pws_campus_distance.csv", index=False)

    ex = attrs[["pwsid", "system_name", "source_water_type", "population_served", "county", "place",
                "lat", "lon", "region", "geocode_method"]].copy()
    dd = dist.merge(camp[["campus_id", "construct_start_year"]], on="campus_id")
    for R in RADII:
        first = dd.loc[dd.distance_km <= R].groupby("pwsid").construct_start_year.min()
        ex[f"g_r{R}"] = ex.pwsid.map(first)
    near = dd.groupby("pwsid").distance_km.min()
    ex["min_campus_km"] = ex.pwsid.map(near)
    ex["nearest_campus"] = ex.pwsid.map(dd.loc[dd.groupby("pwsid").distance_km.idxmin()].set_index("pwsid").campus_id)
    # Host-utility exposure: first construction year among campuses the utility supplies.
    host = camp.groupby("presumed_host_pwsid").construct_start_year.min()
    ex["g_host"] = ex.pwsid.map(host)
    ex["host_link"] = ex.pwsid.map(camp.groupby("presumed_host_pwsid").host_link_status.first())
    # Clean control eligibility.
    ex["control_primary"] = ex.lat.notna() & (ex.min_campus_km > CONTROL_BUFFER_KM) & ex.g_host.isna()
    od = np.array([haversine(r.lat, r.lon, orig.lat.values, orig.lon.values).min() if np.isfinite(r.lat) else np.nan
                   for r in ex.itertuples()])
    ex["min_original_listed_site_km"] = od
    ex["control_strict"] = ex.control_primary & (ex.min_original_listed_site_km > 10)
    ex.to_csv(root / "data/clean/exposure.csv", index=False)
    print(ex.loc[ex.min_campus_km <= 30].sort_values("min_campus_km")
          [["pwsid", "system_name", "min_campus_km", "nearest_campus", "g_r10", "g_r15", "g_r20", "g_host"]]
          .to_string(index=False))
    print("primary controls:", int(ex.control_primary.sum()), " strict controls:", int(ex.control_strict.sum()))


if __name__ == "__main__":
    main()
