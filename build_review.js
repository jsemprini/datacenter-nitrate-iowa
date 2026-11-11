// Builds documents/Iowa_DataCenters_Nitrate_Peer_Review.docx
const c = require("./common");
const { R, A, T2, T3, T3b, DATES, f, fp, pct, ci, comma, P, H1, H2, H3, B, N, small, caption, table, doc, save, AlignmentType, Paragraph, TextRun } = c;

const st = A.static, hr = A.headline_reproduction, cov = A.observed_coverage_of_original_48, sc = A.spatial_counts_code_vs_manuscript;
const M = R.main, host = M["Host utility"], r10 = M["Within 10 km"], r15 = M["Within 15 km"];
const O = R.original_spec_on_observed_data.cohort_construct_10km;
const rej = (s) => s.conventional_cr1_county_rejection_rate_under_placebo;
const neg = T3b[0];
const children = [];
const add = (...x) => children.push(...x);

add(new Paragraph({ style: "Title", children: [new TextRun("Peer review report")] }));
add(P("**Manuscript:** “Misplaced Blame in the Corn Belt? Testing the Causal Impact of Hyperscale Data Center Expansion on Public Drinking Water Nitrate Concentrations in Iowa,” with the technical report (iowa_dc_nitrate_report.md), code (01_fetch_and_clean_data.py, 02_did_equivalence_analysis.py) and facility table, repository datacenter-nitrate-iowa, folder 1-gemini, commit 68148b2.", { after: 60 }));
add(P("**Also assessed:** the replication package in folder 2-oai.", { after: 60 }));
add(P("**Review date:** November 11, 2026 · **Reviewer:** Claude (Anthropic), prepared for the project lead. All checks are reproducible with code/02_audit_original.py and code/04_analyze.py in folder 3-claude.", { after: 200 }));

add(H1("Recommendation: reject"));
add(P(`The manuscript presents generated nitrate and weather values as observed measurements from Iowa DNR, Iowa HHS and the Water Quality Portal. Its central result, that data centers have zero effect bounded within ±0.04 mg/L, is the treatment effect planted in its own simulator plus simulation noise. This is not a problem that revision can fix, because no empirical content remains once the generated data are removed. When the paper's own specification is applied to observed EPA compliance data, its equivalence claim fails. I recommend rejection, withdrawal of all empirical claims from any public version, and a clear disclosure that the original panel is synthetic. A new study built on observed data, along the lines described below and implemented in the accompanying reanalysis, would be welcome.`));

add(H1("Summary of the submission"));
add(P(`The paper asks whether permitting, construction or operation of data centers in Iowa changed nitrate in nearby public water supplies. It reports a 70-facility inventory, a "balanced" 2005Q1–2026Q3 panel of 48 community systems (4,176 system-quarters), two-way fixed effects, Callaway–Sant'Anna and Sun–Abraham estimators, TOST equivalence tests against ±0.25 mg/L and ±0.05 SD, minimum detectable effects, and five mechanism analyses. It concludes that the null hypothesis is "rigorously confirmed," attributes the 2025–2026 Central Iowa nitrate events to agricultural flushing, and recommends that local governments stop linking data center moratoriums to nitrate.`));

add(H1("Major concerns"));
add(H2("1. The outcome data are simulated but described as observed"));
add(P(`The function \`build_pws_nitrate_panels\` creates \`np.random.default_rng(20261111)\` and, for every system-quarter, computes three "samples" from a hand-entered baseline, a seasonal amplitude, a source-type sensitivity, a hand-entered year table and ${st.panel_builder_rng_normal_calls} draws of \`rng.normal\`. It overwrites values for ${st.panel_builder_hardcodes_system_values} named systems, for example by fixing Des Moines Water Works at 7.95–9.17 mg/L in the second and third quarters of 2025–2026 and setting Altoona to 0.30 mg/L plus noise in every quarter. The manuscript and report describe these values as PWS measurements "verified" against state portals and the Water Quality Portal. Rerunning the code reproduces the 4,176-row panel bit for bit (SHA-256 ${A.regenerated.quarter_panel_sha256.slice(0, 16)}…, identical to the hash reported by 2-oai), which confirms that the panel is fully determined by the seed.`));
add(P(`**Required:** disclose that the data are synthetic everywhere the results appear, and remove or retract all empirical and policy conclusions.`));

add(H2("2. The claimed data acquisition does not occur"));
add(P(`The script requests the Water Quality Portal URL but assigns the response to \`_\` and never parses it. If "drop files" are present it logs a message and then runs the same generator, and the function contains no \`read_csv\`. I placed files containing ${comma(A.drop_file_challenge.absurd_value_inserted_mg_l)} mg/L at both drop-file paths and reran the builder. The output was unchanged (maximum system-quarter mean ${f(A.drop_file_challenge.max_mean_nitrate_after_challenge)} mg/L). The portal "barrier manifest" (CAPTCHA, ViewState and other barriers) is not supported by any logged request. Some barriers are real, since the Iowa DNR portal does require interactive queries, but EPA's Six-Year Review files were downloadable throughout and would have supplied observed data for 2006–2019.`));

add(H2("3. The findings are determined by the simulator (circularity)"));
add(P(`The generator adds +${st.planted_grading_pulse_mg_l} mg/L in the construction quarter (Q2–Q3, non-Jordan systems within 10 km) and −${Math.abs(st.planted_land_retirement_slope_per_500_acres)} mg/L per 500 acres from k ≥ 2, with no operational effect. Regressing this planted term alone on the paper's design gives β = ${f(hr.planted_term_on_construct_design_beta, 4)} (construction) and ${f(hr.planted_term_on_operational_design_beta, 4)} (operation). The reported estimates are ${f(hr.reproduced_construct.beta, 4)} (SE ${f(hr.reproduced_construct.se, 4)}) and ${f(hr.reproduced_operational.beta, 4)} (SE ${f(hr.reproduced_operational.se, 4)}), both reproduced exactly here. The "de-fertilization" and "grading pulse" mechanisms, the narrow confidence intervals and the high R² (0.93) all follow from these planted values and the small simulated noise (SD 0.06–0.32 mg/L). The paper therefore recovers its own assumptions.`));

add(H2("4. Weather and mechanism results are artifacts"));
add(P(`Precipitation and temperature "anomalies" come from a hand-entered year table plus quarter offsets and random noise, not from PRISM or the Iowa Environmental Mesonet as stated. The reported precipitation effect (+0.1778 mg/L per SD, p < 0.01) and the conclusion that "post-drought agricultural river flushing—not data center cooling—drove the 2025–2026 Central Iowa Water Works nitrate spikes" have no observational basis. The 2025 and 2026 values for Des Moines and West Des Moines are hard-coded. Agricultural nitrogen may well be the main driver, but this analysis cannot show it.`));

add(H2("5. Estimators are misdescribed and uncertainty is fabricated"));
add(B("The “Callaway–Sant'Anna” standard errors are the stacked-regression SEs multiplied by 1.04 (dynamic) and 1.03 (overall). When a group-time cell is missing, a stacked estimate is substituted. There is no group-time variance estimator."));
add(B("The group-time routine keeps only cohorts from 2008 to 2025, so it silently drops the 2006–2007 cohorts that include Google Council Bluffs and Des Moines. The reported overall ATT (−0.0212) also differs from what the code produces (−0.0163 per 2-oai)."));
add(B("The “Sun and Abraham (2021)” estimator is a stacked regression with never-treated controls, not the interaction-weighted estimator."));
add(B("Treatment is coded by calendar year in a quarterly panel, so a facility starting in November is treated from January. Cumulative acreage and megawatts are assigned at first exposure, which front-loads later expansions."));
add(B("Parallel trends are declared “confirmed” whenever the pre-trend p-value exceeds 0.10. A non-rejection is not confirmation, especially with short or noisy pre-periods (Roth, Sant'Anna, Bilinski and Poe 2023; Rambachan and Roth 2023)."));

add(H2("6. Equivalence testing and power are misapplied"));
add(P(`The ±0.25 mg/L margin is asserted without a decision-based justification, and the same 0.25 is applied to the binary exceedance outcome, where it means 25 percentage points. The ±0.05 SD margin uses the simulated outcome SD. MDEs computed from the realized SE are post hoc. The language that TOST "proves" the effect is "bounded tightly inside ±0.04 mg/L" overstates any equivalence result, which is conditional on the model, the margin and the data. Even with valid data, margins should be pre-specified on the outcome scale, separately for each estimand, and justified by health or regulatory relevance (for example a fraction of the 10 mg/L MCL or the 5 mg/L monitoring trigger).`));

add(H2("7. Exposure data are unverified and partly wrong"));
add(P(`The 70-row facility table mixes greenfield hyperscale campuses (hundreds of acres, large water use) with small colocation suites in existing buildings, and treats both as equivalent exposures. Against documented sources, ${A.dates.outside_documented_interval} of ${A.dates.campuses_compared} hyperscale construction dates fall outside the documented interval. Microsoft Project Mountain is coded as starting construction in April 2009 and operating in June 2011, whereas Microsoft postponed the project in January 2009, the city gave final approval in December 2010, and completion was required by December 2012 (Data Center Knowledge, January 10, 2011). Microsoft Osmium is coded to November 2016, but the first building was planned for spring 2017 and then delayed about 12 months. ${A.coordinates.facilities_within_0_05_km_of_a_pws_point} facilities have coordinates identical to a water system's coordinate (for example ${A.coordinates.examples.slice(0, 3).join(", ")}), which forces distance to zero, and the Meta Altoona site is placed ${f(DATES.find((x) => x.campus_id === "META_ALT").original_vs_documented_location_km, 1)} km from its documented location. "Same municipality" is a city-name match, and the "upstream HUC-10" relation is a hand-written dictionary without flow-direction data. The counts of ever-treated systems in the text do not match the code (municipality ${sc.same_municipality[1]} reported vs ${sc.same_municipality[0]} in code; 10 km ${sc["10km"][1]} vs ${sc["10km"][0]}; HUC-10 ${sc.huc10[1]} vs ${sc.huc10[0]}).`));

add(H2("8. The unit of analysis, independence and monitoring are mis-specified"));
add(P(`${cov.original_text_says_purchased_or_ciww} of the 48 systems are described in the paper's own metadata as purchasing water from Central Iowa Water Works or Des Moines Water Works. Their finished water is largely the same water, so they are not independent observations, and clustering by HUC-10 or county does not capture the shared supply. In EPA's 2012–2019 compliance data, ${48 - cov.with_own_entry_point_records_2012_2019} of the 48 systems (${cov.without_records.slice(0, 6).join("; ")}; and others) have no nitrate samples of their own, and the remaining ${cov.with_own_entry_point_records_2012_2019} contribute ${cov.observed_pws_years_2012_2019} system-years, mostly from one annual sample. A balanced quarterly panel of three samples per quarter does not exist for these systems. Groundwater systems below half the MCL are typically sampled annually, and sampling frequency rises with nitrate, so the "quarterly maximum" and exceedance outcomes are not comparable across systems.`));

add(H2("9. Pooling ignores hydrology"));
add(P(`Sixteen of the 48 systems draw from confined bedrock aquifers (Jordan, Silurian), where land-surface nitrogen cannot arrive on the study's time scale. Including them adds precision without information. The plausible pathways (construction runoff to downstream intakes or shallow wells, demand-driven changes in a host utility's source blend, and blowdown discharged downstream) each imply a specific set of exposed systems. Distance buffers of 5–20 km around city centroids do not identify any of them. River intakes downstream of campuses can be bounded with a simple mass balance, and for the Raccoon River this bound is below about 0.1 mg/L at mean flow and 0.2 mg/L at median flow even under extreme export assumptions (manuscript Table 5).`));

add(H2("10. The claims do not hold with observed data"));
add(P(`Using EPA SYR4 compliance data (2012–2019) for the ${O.n_systems} original systems that have their own samples, the paper's 10 km two-way fixed-effects specification gives β = ${f(O.beta)} mg/L (SE ${f(O.se_cr1_huc10)}; 90% CI ${ci(O.tost_0_25.ci90[0], O.tost_0_25.ci90[1])}). This interval is not inside ±0.25 (TOST p = ${fp(O.tost_0_25.p_tost)}), so the equivalence claim fails under the paper's own method. A redesigned analysis (documented campus dates; host-utility and distance exposures; stacked imputation estimator; randomization inference) finds ${f(host.att)} mg/L for host utilities (95% randomization confidence set ${ci(host.ri_ci95[0], host.ri_ci95[1])}) and ${f(r10.att)} within 10 km (${ci(r10.ri_ci95[0], r10.ri_ci95[1])}). Observed data can exclude effects larger than about 1 mg/L, not 0.04 mg/L. A 15 km design produced a spurious positive estimate (${f(r15.att)}) driven by Des Moines Water Works. Treated as a negative-control exposure, that utility shows a ${f(neg.att, 1)} mg/L "effect" that cannot be causal. Conventional county-clustered tests rejected the true null in ${pct(rej(host).alpha_0_05)} of placebo host assignments. These results illustrate how little precision the real data allow and how easily proximity designs produce artifacts in either direction.`));

add(H2("11. Framing, advocacy and disclosure"));
add(P(`The generating prompt names the null as the "primary working hypothesis" and the framing document asks the paper to show that blaming data centers "diverts policy interventions." The title ("Misplaced Blame"), the language of proof and the policy recommendations follow that framing rather than the evidence. The byline lists a department and initiative that I could not verify, and the paper does not disclose that it was produced by an AI system or that its data are synthetic. Several water-quality facts are sourced to commercial filtration-vendor pages (Kind Water Co., Prime Flow Filtration, PurityMap) instead of utility consumer confidence reports or DNR records. A revised study should disclose AI use and authorship, pre-specify hypotheses neutrally, and cite primary sources.`));

add(H1("Minor concerns"));
[
  "Internal inconsistencies: the surface-water stratum effect (+0.0502; 90% CI +0.0155 to +0.0849) and the deep-aquifer effect (+0.0065; CI +0.0002 to +0.0128) exclude zero yet are described as showing no impact, and the grading pulse is called “statistically insignificant” while its 90% CI excludes zero.",
  "The facility table has 20 distinct counties and 6,606.5 MW in summed capacity, while the text reports 18 counties and 6,200 MW “deduplicated” without a documented reconciliation.",
  "A common MDL of 0.10 mg/L is assumed. Observed reporting limits vary, and most non-detects in Iowa compliance data have limits of 1 mg/L or more, which matters far more than the √2 convention.",
  "The nitrate-ion conversion step is applied to values that were generated in mg/L as N and then converted back. It demonstrates nothing about real unit heterogeneity.",
  "“First mandatory lawn-watering ban in Des Moines metropolitan history” and the 2026 statements (193-day nitrate-removal run, a 12-county moratorium wave, a West Des Moines Water Works white paper, a Linn County MOU) need primary citations. The 2025 ban and river levels are corroborated by Iowa Public Radio, the Axios fact-check exists, and a Linn County moratorium was reported, but other specifics could not be verified.",
  "JEL codes, a working-paper series and a departmental affiliation imply an institutional review that did not occur.",
].forEach((t) => add(B(t)));

add(H1("Spot-check of contextual and exposure claims"));
add(table(["Claim in manuscript", "Status", "Source checked"], [
  ["CIWW lawn-watering ban began June 12, 2025; river nitrate ~15 mg/L, highest since 2013", "Verified", "Iowa Public Radio, June 17, 2025"],
  ["Axios fact-check: data centers not to blame (June 17, 2025)", "Verified (data centers 2–7% of WDM water)", "Axios Des Moines"],
  ["Raccoon River peak 20.55 mg/L; finished water 9.17 mg/L", "Not verified", "Cited press release not retrieved"],
  ["Microsoft Mountain: construction Apr 2009, operation Jun 2011", "Contradicted", "DCK (2011): postponed 2009, approval and dirt-moving Dec 2010, completion by Dec 2012"],
  ["Microsoft Osmium: permitted 2016, construction Nov 2016", "Partly contradicted", "Revealed Jul 2016; first building planned spring 2017, delayed ~12 months (DCD, Business Record)"],
  ["Meta Altoona B1: construction 2013, online Nov 2014", "Verified", "Meta (2021); TechCrunch (Nov 14, 2014)"],
  ["Apple Waukee: approved Aug 2017, main construction 2022, online 2024", "Verified", "Apple newsroom (2017); DCD (groundwork Mar 2022; operating 2024)"],
  ["Google Council Bluffs Campus 1: 2007 start, 2009 operation", "Partly verified (first data center completed 2008)", "DCK (Dec 2013)"],
  ["Meta cooling water from Altoona's Jordan wells", "Not verified (Altoona uses Jordan wells; supply to Meta undocumented)", "City of Altoona water FAQ"],
  ["Twelve Iowa counties enacted or advanced moratoriums in 2026", "Not verified (Linn County moratorium reported)", "Corridor Business Journal"],
], [3900, 2200, 3260]));

add(H1("Assessment of the replication package (2-oai)"));
add(P(`The 2-oai package correctly identified the fatal problems (generated outcomes and weather, non-functional ingestion, variance multipliers, estimator mislabeling, count discrepancies), froze the original code, and declined to substitute generated data. My independent audit confirms each of these findings and reproduces its panel hash. Its observed-data pipeline (EPA SYR4 extract with hashes, censoring intervals, no filling) is a sound foundation, and I reused its Iowa extract after verifying the hash.`));
add(P("However, the package stops short of answering the research question, and several choices can be improved:"));
add(N("**Stage classification is unnecessarily conservative.** It labels 96.9% of routine community samples \"unresolved.\" EPA's SYR4 QA/QC guide gives rules for records without a source code, and inorganic compliance samples are by regulation taken at entry points (40 CFR 141.23). Applying these rules resolves almost all records (16,603 entry-point, 394 raw).", "num0"));
add(N("**No exposure design was attempted.** Construction dates and locations for the major campuses are documented in public sources. The package's template marks every system \"unresolved\" and its estimator refuses to run, so the replication provides no evidence on the substantive question.", "num0"));
add(N("**The inference gate removes the only feasible designs.** Requiring at least 10 supply clusters for a bootstrap is reasonable, but randomization inference, negative controls and physical bounds remain valid with one to three exposed units, which is the actual situation.", "num0"));
add(N("**SYR3 (2006–2011) was not pursued.** Without it the 2007 and 2010 cohorts have no baseline. The new extraction script includes an SYR3 path.", "num0"));
add(N("**Physical plausibility was not quantified.** A mass balance using published flows and nitrogen yields bounds the river-intake pathway more tightly than any regression the data allow.", "num0"));
add(N("**Minor:** the observed-coverage figure counts systems appearing in the release rather than systems required to monitor, so absence cannot be read as non-compliance. 2-oai notes this, but the figure could make it clearer.", "num0"));

add(H1("What a publishable study would need"));
[
  "Observed outcomes only, with provenance hashes. Use SYR3 and SYR4 compliance data plus Iowa DNR results for 2020–2026, keeping raw and entry-point samples separate and retaining censoring intervals.",
  "Documented, dated exposure events for hyperscale campuses (first land disturbance, first withdrawal, discharge start), each with a source. Colocation suites should be excluded or analyzed separately.",
  "Exposure defined by pathway: host utility (supply network), downstream surface intakes (NHDPlus flow lines), and shallow wells within capture zones. Consecutive systems should be grouped with their wholesaler.",
  "Estimators robust to staggered timing (imputation, Callaway–Sant'Anna or stacked designs) with design-based inference for few exposed units, plus negative controls and leave-one-event-out analyses.",
  "Pre-specified equivalence margins on the concentration scale, separate margins for probability outcomes, and statements of what the design can and cannot exclude.",
  "Mechanism analysis using measured weather (PRISM or IEM), river nitrate (USGS and utility data), and utility operating records (blend shares, nitrate-removal run days and capacity, data center demand by month).",
  "Clear disclosure of AI involvement and neutral framing of hypotheses.",
].forEach((t) => add(N(t, "num1")));
add(small("The accompanying manuscript (3-claude) implements items 1–5 for 2012–2019 within the data access available, and documents the gaps that remain.", { after: 120 }));
add(H1("References cited in this review"));
[
  "Data Center Knowledge (2011, January 10). Microsoft starts building Iowa data center.",
  "Data Center Dynamics. Microsoft delays West Des Moines Osmium data center build; Business Record. Microsoft West Des Moines projects.",
  "Iowa Public Radio (2025, June 17); Axios Des Moines (2025, June 17); Corridor Business Journal (2026). Linn County data center moratorium approved.",
  "U.S. EPA (2024). Six-Year Review 4 compliance monitoring data and QA/QC guide; 40 CFR 141.23.",
  "Roth J, Sant'Anna PHC, Bilinski A, Poe J (2023). What's trending in difference-in-differences? Journal of Econometrics 235(2):2218–2244.",
  "Rambachan A, Roth J (2023). A more credible approach to parallel trends. Review of Economic Studies 90(5):2555–2591.",
  "Callaway B, Sant'Anna PHC (2021); Sun L, Abraham S (2021). Journal of Econometrics 225(2).",
  "Conley TG, Taber CR (2011). Review of Economics and Statistics 93(1):113–125; MacKinnon JG, Webb MD (2018). Econometrics Journal 21(2):114–135.",
  "Lakens D (2017). Equivalence tests: a practical primer. Social Psychological and Personality Science 8(4):355–362.",
].forEach((t, i) => add(new Paragraph({ children: [new TextRun({ text: `[${i + 1}] `, size: 17, bold: true }), new TextRun({ text: t, size: 17 })],
  spacing: { after: 50, line: 240 }, indent: { left: 400, hanging: 400 } })));

save(doc(children, "Peer review report", "Peer review · datacenter-nitrate-iowa (1-gemini)"), "documents/Iowa_DataCenters_Nitrate_Peer_Review.docx");
