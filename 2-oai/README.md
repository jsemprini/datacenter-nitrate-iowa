# Iowa data centers and nitrate audit

The original causal conclusion is unsupported. Its nitrate outcomes and weather
controls are generated, and claimed group-time standard errors are borrowed by
fixed multipliers. This package reproduces that behavior and supplies a separate
observed-data workflow. It does not estimate a valid statewide data-center effect.

## Start here

- `documents/`: fresh manuscript, two-page brief and independent peer review in Word and PDF.
- `Iowa_Data_Centers_Nitrate_Colab.ipynb`: standalone Colab notebook with the observed extract and executable code embedded. Uploading the ZIP is not necessary to run it.
- `results/`: observed coverage tables, discrepancies, reference-link checks, acquisition records and software checks.
- `data/raw/`: actual EPA Iowa nitrate extract, release documentation, DNR index and a separate WQP ambient query.
- `data/clean/`: actual sample-level data, separate stage-specific quarterly/annual panels and coverage grid.
- `source_original/`: frozen supplied project at commit `7e1f0e6d2a3c053a47ed9d90b45e894a9e02066a`.
- `forensic_reproduction/SYNTHETIC_OUTPUTS/`: generated outcomes and replicated estimates, retained solely as audit evidence. These are not observed Iowa water data.

## Run the observed-data workflow

From the extracted package directory, with Python 3.11 or later:

```bash
python -m pip install -r requirements.txt
python code/01_clean_data.py
python code/02_analyze_data.py
python code/03_verify_pipeline.py
```

The small observed extract is bundled, so these commands require no network.
To repeat acquisition from primary sources:

```bash
python code/00_extract_public_data.py --wqp-year 2020
```

This downloads a roughly 89 MiB national EPA archive to `cache/`, checks the audited
release hash, and streams only the Iowa nitrate records into `data/raw/`.
The national archive is not bundled. The extractor fails instead of substituting
observations if download, checksum or schema checks fail. A changed release needs
explicit review before changing the expected hash. WQP ambient records are kept
separate from PWS compliance samples because a validated source crosswalk is absent.

## What was executed

The original data and estimation paths were reviewed before execution. The forensic runner
redirects output/copy destinations and disables network response retrieval that
the original code discards. It leaves the original outcome generator and
estimators unchanged. It regenerates 4,176 quarterly rows and repeats the
extreme-input ingestion challenge. Run:

```bash
python code/05_reproduce_original.py
```

The original script's optional `statsmodels` and `linearmodels` imports are not
required by the executed custom-OLS path. The supplied raw source scripts remain
unchanged. `code/04_audit_reference_links.py` rechecks the 50 embedded HTTP URLs;
this optional link-check command also needs `pypdf`. HTTP 403 denotes an access
response, not proof that a reference is invalid. Link status does not establish
substantive citation support.

## Observed results

The EPA release contains 28,103 Iowa-filtered nitrate records and 1,649 systems
for 2012–2019. Four confirmation community samples and two community samples
without usable numeric information are excluded, leaving 17,011 routine
community samples from 845 systems. Of these, 16,489 have unresolved source stage,
521 have finished/entry/distribution codes, and one has raw-water coding.
Known-stage classification does not validate source connectivity or an individual
customer's exposure.

Usable observations occupy 9,866 of 27,040 possible system-quarter cells among
community systems appearing in this release. Missing quarters remain missing.
Only 38 of the original 48 systems have records in this release. Those data do
not extend through 2026, so no 2025–2026 effect or mechanism is estimated.

## Causal analysis gate

`data/exposure_design_template.csv` deliberately marks all 48 named systems and
both phases as unresolved. It is not a treatment assignment file. Before using
the optional estimator, replace it with independently reviewed source/supplier
evidence and ascertain both exposure and controls through the analysis cutoff.
Required fields and additional records are described in `data/required_inputs.json`.

```bash
python code/02_analyze_data.py --design reviewed_exposure.csv --phase construction --stage finished_or_entry --bootstrap 999
```

The optional implementation estimates unadjusted paired group-time changes using
clean never/not-yet-treated controls. It recomputes uncertainty by resampling supply
clusters, provides pointwise and simultaneous event-time uncertainty, excludes
unsupported cells, and stops on inadequate bootstrap support. It is not advertised
as a full CS doubly robust implementation or Sun–Abraham estimator. It does not
address endogenous monitoring, differential trends or confounding merely by
running. Weather, agricultural activity, supplier changes and treatment histories
must be assessed in an actual completed study. No adjusted model is represented
as having run without those data.

Default sample eligibility requires four observed pretreatment quarters, a paired
baseline and follow-up, and a comparison group. The default event range is −8 to
+12 quarters. Report the changing cohort composition and prefer a common-cohort
window where support permits. Operation is a separate phase; an operation-only
contrast does not identify an incremental effect beyond prior construction.

## Measurement and weighting

- Regulatory analyte 1040 is interpreted as nitrate as nitrogen. Convert result
  and limit units independently. The hybrid-nitrate file is excluded to avoid
  duplicate records and mixing nitrate/nitrite substitutions.
- Keep non-detect bounds `[0, reporting limit]`. `nitrate_mid` uses limit divided by
  square root of two as a descriptive convention; bounds remain available.
- Average samples within point-quarter, points equally within PWS-quarter-stage,
  and observed quarters equally within year. Report sample/point/quarter counts.
  These are not flow or population weights.
- Raw, finished/entry, unresolved and contradictory stages remain separate.
  `observed_max` is a sample-derived upper value, not a continuously measured peak.
- `coverage_grid.csv` creates a reporting grid, not a filled outcome panel.
  Do not replace its missing observations with zero, forward fill or interpolation.

## Verification

Eight scientific software checks passed: unit/limit conversion, contradictory
stage handling, preservation of missing quarters, duplicate-ID rejection,
paired-comparison composition, unresolved-exposure rejection, equivalence versus
non-significance, and a nondegenerate cluster bootstrap on an explicitly artificial
fixture with a known effect. The tests validate code behavior, not causal assumptions.
Manuscript, brief and review were rendered and visually inspected before delivery.

## Provenance

Primary sources and exact URLs are in `data/primary_sources.json` and the manuscript.
File hashes are in `manifest_sha256.json`. The original generated output hash and
challenge-test result are in `forensic_reproduction/SYNTHETIC_OUTPUTS/reproduction_checks.json`.
All generated forensic outputs are segregated from observed records.
