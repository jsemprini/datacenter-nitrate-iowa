# 3-claude: audit, replication and reanalysis

This folder audits the original analysis (`1-gemini`), assesses the replication package (`2-oai`), and replaces
the generated panel with a reanalysis built on **observed** EPA compliance data and documented data center events.

## Main findings

1. **Original (1-gemini):** every nitrate and weather value is produced by `np.random.default_rng(20261111)`
   with a planted treatment term (+0.022 mg/L pulse, −0.015 mg/L per 500 acres). External data are never read:
   inserting 987,654 mg/L at the claimed drop-file paths changes nothing. The headline β = +0.0013 (SE 0.0178)
   reproduces exactly, so it reflects the simulator's assumptions rather than Iowa water.
2. **Original specification on observed data:** β = −0.16 mg/L (SE 0.19). The ±0.25 mg/L equivalence test fails
   (TOST p = 0.33).
3. **Redesigned analysis (EPA SYR4, 2012–2019):** new-campus construction starts (Meta 2013, Microsoft Alluvion
   2014, Microsoft Osmium 2018) show no detectable effect.
   - Host utility: −0.14 mg/L (randomization p = 0.55; 95% set −0.98 to 0.76).
   - Within 10 km: −0.14 mg/L (95% set −1.05 to 0.74).
   - The data rule out effects larger than about ±1 mg/L, not ±0.04.
   - A +0.69 estimate at 15 km is bias from regional river nitrate. A negative control (Des Moines Water Works ×
     Meta) shows a spurious +2.6 mg/L.
4. **Physical bound:** documented central-Iowa campus land is 0.049% of the Raccoon basin. Even under extreme
   nitrogen-export assumptions it adds ≤0.07 mg/L at mean flow (≤0.18 at median flow).
5. **Conventional cluster-robust tests** rejected true placebo nulls 23–45% of the time at nominal 5%. With one
   to seven exposed systems, randomization inference is required.

## Layout

| Path | Contents |
|---|---|
| `code/00_extract_public_data.py` | Acquisition with SHA-256 checks: EPA SYR4 (falls back to the hash-verified 2-oai Iowa extract pinned to a commit), optional SYR3 (`--syr3`), GeoNames places |
| `code/01_clean_data.py` | Units, censoring intervals, EPA stage rules, PWSID county decoding, geocoding, annual panel (no filling) |
| `code/02_audit_original.py` | Forensic audit of 1-gemini: static checks, isolated re-execution, drop-file challenge, planted-effect recovery, date/coordinate/coverage checks |
| `code/03_build_exposure.py` | Distances, host links, radius exposures, control sets |
| `code/04_analyze.py` | Stacked imputation DiD, randomization inference with test-inversion confidence sets, negative control, sensitivity analyses, original spec on observed data, mass balance, figures |
| `code/05_verify_pipeline.py` | 25 verification checks (provenance, cleaning, estimator correctness on labeled artificial fixtures, RI size, reproducibility) |
| `code/nitrate_lib.py` | Shared estimators |
| `code/docs/*.js` | Build the manuscript, brief and review from `results/` and `audit/`, so no numbers are typed by hand |
| `data/reference/` | Documented campus table with sources, mass-balance inputs with sources, original facility table (unverified, used only for a strict control screen) |
| `data/raw/`, `data/clean/` | Observed extract and derived tables |
| `audit/` | Audit outputs, including `audit_results.json` |
| `results/` | `results.json`, tables, figures, `verification_report.json` |
| `documents/` | Manuscript, policy brief and peer review report (.docx and .pdf) |

## Run

```bash
python -m pip install -r requirements.txt     # Python 3.11+
bash run_all.sh                               # about 5 minutes; documents need Node + the `docx` npm package
```

`run_all.sh` runs steps 00–05 and then builds the documents. For the longer 2006–2019 window, run
`python code/00_extract_public_data.py --syr3` in an environment that can reach epa.gov. That path is schema-checked
but was **not executed** for the reported results, because EPA, Iowa DNR, USGS and NOAA hosts were blocked by the
network policy of the computing environment used here.

## Relationship to 2-oai

The 2-oai audit is confirmed: the panel hash matches, and the ingestion and SE-multiplier findings hold. This
folder makes four changes:

- Water stage is resolved with EPA's SYR4 rules and 40 CFR 141.23, instead of leaving 96.9% of records "unresolved".
- A documented exposure design is built, and effects are estimated with randomization inference rather than withheld.
- Negative controls and mass-balance bounds are added.
- The original specification is re-run on observed outcomes.

## Limitations

- Data end in 2019.
- Only three events and two host utilities are informative.
- Host links other than Microsoft–West Des Moines Water Works are presumed.
- Some coordinates are approximate (1–3 km).
- Reporting limits of 1 mg/L hide small changes.
- Flow paths were not checked with NHDPlus.

Prepared with Claude (Anthropic). Authors should verify before circulation.
