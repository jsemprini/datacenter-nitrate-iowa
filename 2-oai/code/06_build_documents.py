"""Build the fresh manuscript, two-page brief, and independent review in Word.
Render PDFs using the document renderer in the authoring environment.
"""
from pathlib import Path
import json
import pandas as pd
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'documents';OUT.mkdir(exist_ok=True)

def document(font='Cambria',size=11):
    d=Document();s=d.sections[0]
    s.top_margin=s.bottom_margin=Inches(.68);s.left_margin=s.right_margin=Inches(.78)
    s.page_width=Inches(8.5);s.page_height=Inches(11)
    for name in ['Normal','Body Text']:
        st=d.styles[name];st.font.name=font;st.font.size=Pt(size)
        st.paragraph_format.space_after=Pt(6);st.paragraph_format.line_spacing=1.07
    for name,sz in [('Title',23),('Subtitle',12),('Heading 1',13),('Heading 2',11.5)]:
        st=d.styles[name];st.font.name=font;st.font.size=Pt(sz);st.font.color.rgb=RGBColor(0,0,0)
        st.paragraph_format.space_before=Pt(11);st.paragraph_format.space_after=Pt(6)
    for st in d.styles:
        if st.element.pPr is not None:
            for border in list(st.element.pPr.findall(qn('w:pBdr'))):st.element.pPr.remove(border)
    p=s.footer.paragraphs[0];p.alignment=2
    f=OxmlElement('w:fldSimple');f.set(qn('w:instr'),'PAGE')
    rr=OxmlElement('w:r');tt=OxmlElement('w:t');tt.text='1';rr.append(tt);f.append(rr);p._p.append(f)
    d.core_properties.title='Data centers and nitrate in Iowa public water supplies'
    d.core_properties.author=''
    return d

def title(d,a,b):
    d.add_paragraph(a,'Title');d.add_paragraph(b,'Subtitle')
    p=d.add_paragraph('November 11 2026');p.paragraph_format.space_after=Pt(12)
def h(d,t):
    z=d.add_paragraph(t,'Heading 1')
    if getattr(d,'_next_heading_newpage',False):
        z.paragraph_format.page_break_before=True
        d._next_heading_newpage=False
def p(d,t):d.add_paragraph(t)
def bullet(d,t):d.add_paragraph(t,'List Bullet')
def page(d):d._next_heading_newpage=True
def table(d,heads,rows,widths=None):
    t=d.add_table(rows=1,cols=len(heads));t.style='Table Grid'
    for c,txt in zip(t.rows[0].cells,heads):c.text=str(txt)
    for row in rows:
        for c,txt in zip(t.add_row().cells,row):c.text=str(txt)
    for i,row in enumerate(t.rows):
        pr=row._tr.get_or_add_trPr();el=OxmlElement('w:cantSplit');pr.append(el)
        if i==0:
            el=OxmlElement('w:tblHeader');pr.append(el)
        for j,c in enumerate(row.cells):
            if widths:c.width=Inches(widths[j])
            if i==0:
                sh=OxmlElement('w:shd');sh.set(qn('w:fill'),'E8EDF2');c._tc.get_or_add_tcPr().append(sh)
            for para in c.paragraphs:
                para.paragraph_format.space_after=Pt(4);para.paragraph_format.space_before=Pt(3)
                for r in para.runs:r.font.size=Pt(9.4);r.bold=i==0
    return t

def caption(d,t):
    z=d.add_paragraph(t);z.paragraph_format.space_after=Pt(7)
    for r in z.runs:r.font.size=Pt(9.3)

def manuscript():
    d=document()
    title(d,'Data centers and nitrate in Iowa public water supplies','A reproducibility audit and analysis of public monitoring data')
    h(d,'Abstract')
    p(d,'Background  A public research repository reported that data-center construction and operation had essentially zero causal effects on nitrate concentrations in Iowa public water supplies during 2005–2026. We assessed whether its data and computations support that conclusion and developed an observed-data replacement workflow.')
    p(d,'Methods  We froze repository commit 7e1f0e6d2a3c053a47ed9d90b45e894a9e02066a, inspected the source code and manuscript, re-executed the analysis in an isolated output directory, and tested whether an external nitrate input altered the results. We independently downloaded EPA Six-Year Review 4 nitrate records for 2012–2019, verified the named public water-system identifiers against Iowa’s public index, and constructed sample-level censoring intervals and unbalanced monitoring panels.')
    p(d,'Results  The original code generated all 4,176 quarterly nitrate outcomes and their weather covariates rather than analyzing retrieved measurements. Its headline construction and operation estimates reproduced to reported precision, but supplying an extreme external nitrate record changed no output. The purported Callaway–Sant’Anna standard errors were scaled versions of stacked-regression standard errors. Several spatial counts and staggered estimates differed from the written report. The independently acquired EPA data contained 28,103 nitrate records from 1,649 systems, including 17,011 usable routine community-system samples from 845 systems. Of these community samples, 16,489 (96.9%) had unresolved water-stage labels. Observations covered 9,866 of 27,040 possible system-quarter cells among community systems appearing in the release.')
    p(d,'Conclusions  The repository’s causal null, equivalence, and weather-attribution claims are unsupported. This audit establishes neither harm nor absence of harm from data centers. A valid study requires observed raw and finished water records, independently documented construction and withdrawal dates, physical source and supply-network links, and inference reflecting the number of independent exposed water systems.')
    p(d,'Keywords  Iowa; nitrate; data centers; reproducibility; public water systems; difference in differences')

    page(d);h(d,'Introduction')
    p(d,'Data-center development raises distinct questions about water demand, water-source changes, treatment capacity, and contaminant concentrations. These questions can overlap operationally without having the same causal answer. During the 2025 Central Iowa Water Works conservation response, the utility documented high source-water nitrate and constraints on producing enough treated water. These records establish a water-quality and capacity problem; they do not identify the contribution of data centers to nitrate concentrations. [1,6]')
    p(d,'The audited manuscript combined this policy debate with a statewide difference-in-differences analysis and formal equivalence tests. Its main interpretation was stronger than a failure to reject a treatment effect: it asserted zero impact and attributed nitrate spikes to agricultural flushing rather than cooling demand. Such conclusions require a documented connection between observed samples, actual facility events, and a credible comparison group. Reproducible numerical calculations alone cannot establish those connections.')
    p(d,'Our objectives were to verify data provenance, reproduce the submitted computations, identify material methodological errors, and determine what an independently acquired public dataset can support. The resulting manuscript reports an audit and observed-data feasibility analysis. It does not substitute generated observations for a missing causal study.')
    h(d,'Audit methods')
    p(d,'We obtained all files in the repository’s 1-gemini directory through GitHub and retained the commit identifier and file hashes. Materials included two Python scripts, a 70-row facility CSV, the manuscript PDF, a technical report, a media article, and prompt and framing documents. We inspected data-flow paths before executing code. To contain the original scripts’ file-copying behavior, we imported their functions and redirected OUTPUT_DIR and WORKSPACE_ROOT into a dedicated forensic directory. Their network-fetch hook was replaced with an empty response because the original functions discard the returned response. The original estimator and data-generation expressions were unchanged. [1]')
    p(d,'We regenerated the quarterly and annual panels and all reported analysis outputs. To test actual ingestion, we placed an external CSV in the path the script checks, containing a nitrate value of 987654.321 mg/L for Des Moines. We regenerated the panel and compared SHA-256 hashes. This deliberately implausible value was a software challenge input; it was not a water measurement and was never used in the observed-data analysis.')
    p(d,'We separately parsed Iowa DNR’s Source Water Protection Tracker index and matched all 48 system IDs used by the original project. We checked selected primary source-water descriptions and a Meta expansion announcement. We also tested the HTTP accessibility of 50 unique URLs embedded in the original manuscript. A successful HTTP response was treated only as link availability, not as validation that the page supports a cited claim. [4,7]')

    page(d);h(d,'Findings on original data provenance')
    p(d,'The function build_pws_nitrate_panels creates a NumPy random generator with seed 20261111. For each of 48 manually described systems and 87 quarters, it computes nitrate values from a hand-entered baseline, seasonal amplitude, source-type sensitivity, manually assigned yearly climate values, and random noise. It then inserts specific values for selected systems and years. Its constructed treatment mechanism adds a small grading pulse and later subtracts an acreage-dependent quantity. Operational status is not given an independently measured nitrate response. These design choices determine the substantive patterns that the subsequent models recover.')
    p(d,'The source file includes neither a parser for the returned Water Quality Portal content nor a read_csv call for the purported raw nitrate drop files. File existence triggers a log message, after which the same generator runs. The external-file challenge produced an identical quarterly-panel hash. The 912 rows labeled as cleaned sample data are a selected preview of generated values; they are not the full set of measurements underlying the generated quarterly averages. The fully populated panel therefore does not demonstrate complete historical monitoring coverage.')
    p(d,'The original weather covariates also come from a hand-entered year table, quarter offsets, and random perturbations. They are not retrieved PRISM or Iowa Environmental Mesonet measurements. A precipitation coefficient from this system cannot identify the actual causes of the 2025–2026 nitrate events. Neither residualizing on these covariates nor adding fixed effects restores empirical content to generated outcomes.')
    h(d,'Table 1 Reported and reexecuted estimates')
    rows=[['Construction TWFE','+0.0013','+0.00129','0.01782'],['Operation TWFE','−0.0124','−0.01238','0.01420'],['Claimed group time ATT','−0.0212','−0.01627','0.02082'],['Stacked static ATT','+0.0018','−0.00747','0.02021']]
    table(d,['Quantity','Reported','Reexecuted','Reexecuted SE'],rows)
    caption(d,'Units are mg/L as N. Every estimate in this table uses generated outcomes and has no evidentiary value for Iowa water quality. The first two reported values are from the manuscript abstract; the group-time value is from manuscript Table 3; the stacked static value is from the Markdown report summary. Displayed group-time SE is the original code’s unsupported scaled SE, reproduced only for forensic comparison.')
    p(d,'All 48 named PWS identifiers matched the DNR index, and the re-created 70-row facility table matched the repository CSV after CSV parsing. These successful checks validate identities and file reproducibility. They do not validate facility coordinates, project completeness, exact dates, capacities, water-source links, or the nitrate time series. The script’s facility CSV contains 20 distinct county names and 6,606.5 MW in summed capacity fields; the narrative’s 18 counties and deduplicated capacity require a separate, documented reconciliation.')

    page(d);h(d,'Findings on design and inference')
    p(d,'The purported Callaway–Sant’Anna routine calculates some cohort-time differences, but does not compute the sampling covariance of those estimates. Instead, it sets each dynamic standard error to se_stacked multiplied by 1.04 and the overall standard error to se_stacked multiplied by 1.03. When a cohort-time estimate is unavailable, it substitutes a stacked estimate. These operations are not a valid variance estimator or a principled treatment of unsupported event times. The stacked regression is also not the cohort-by-event interaction-weighted Sun–Abraham estimator named in the manuscript. [8,9]')
    p(d,'The cohort-time routine excludes 2006 and 2007 cohorts despite the presence of four such treated systems, including Des Moines and Council Bluffs. Calendar years, rather than the available quarter dates, determine treatment in the quarterly panel, so facilities starting late in a year can be coded as treated from the first quarter. The mechanism variables activate the sum of all linked campus acreage or power at first exposure, assigning later expansions to earlier periods. An operation-only regression after construction has already begun does not isolate the incremental effect of cooling activation.')
    h(d,'Table 2 Spatial treatment counts')
    table(d,['Definition','Manuscript count','Code count'],[['Same municipality','15','19'],['Within 5 km','15','21'],['Within 10 km','21','31'],['Within 20 km','29','37'],['Shared or mapped HUC10','24','34']])
    caption(d,'Manuscript counts are from the data section. Code counts are distinct systems flagged as ever treated among the 48 hard-coded systems. These are computational discrepancies, not validation of the exposure definitions.')
    p(d,'Municipality matching compares city names, not service-area polygons. Distance calculations use hard-coded system coordinates without evidence that they locate relevant intakes or wellheads. The “upstream” definition is a manually supplied HUC10 adjacency list. Shared hydrologic-unit membership alone does not establish flow direction or a groundwater capture-zone connection. Purchased-water systems also create supply-network dependencies that a proximity or local-watershed cluster may miss.')
    p(d,'The TOST formula in the original static-regression routine is recognizable, but a correct formula applied to generated outcomes cannot demonstrate real-world equivalence. The 0.25 mg/L margin is not justified by a clinical or policy loss function; applying the same numeric margin to a binary exceedance outcome instead tests a 25-percentage-point margin. The standardized margin uses the generated outcome SD. The “MDE” is a post hoc approximation based on that SE, not evidence about power in an actual monitoring design.')
    p(d,'Finally, a nonsignificant pretrend test does not confirm parallel trends. Few treated clusters, sparse event-time support, common suppliers, and selection into monitoring can all limit the informativeness of such a test. The project’s strong claims about parallel trends, mechanism attribution, and a flat zero effect exceed what even an otherwise valid observational DiD would establish. [10,11]')

    page(d);h(d,'Independent observed data and cleaning')
    p(d,'We downloaded EPA’s released Six-Year Review 4 chemical-occurrence archive and streamed the SUMMARY_ANALYTE_NITRATE.txt member, retaining STATE_CODE IA and analyte 1040. The archive SHA-256 was 5b8726c9adee8fbfa0ca265393814439d0f5d1a552b7a88b0322d19ec9d738e0. The source covers January 2012 through December 2019; it cannot directly assess events in 2025–2026. We did not append the hybrid-nitrate member because it overlaps nitrate records and includes nitrate/nitrite substitutions. [2,3]')
    p(d,'We preserved the original identifiers, result and detection-limit fields, collection dates, source-stage and sampling-point codes. The national text file required cp1252 decoding. The Iowa state filter also returned 17 records with federally administered numeric system IDs, which we preserved rather than forcing into Iowa-prefixed identifiers. Exact duplicate rows were removable, whereas conflicting duplicate analytical IDs would stop the pipeline. No such duplicate IDs were present.')
    p(d,'EPA analyte 1040 represents regulatory nitrate; results were interpreted on the nitrate-as-nitrogen basis used for the federal standard. All detected Iowa values were in micrograms per liter and were divided by 1,000. Detection-limit units were converted independently, predominantly from mg/L. For non-detects, we retained the interval from zero to the reported sample-specific limit. The limit divided by the square root of two was used only as a descriptive midpoint convention. We did not assume a common 0.10 mg/L detection limit or treat non-detects as measured zero. Six records lacked usable numeric information. [3,5]')
    p(d,'The descriptive community sample was restricted to system type C, routine sample type RT, and usable results or censoring intervals. Source code RW or point codes RW/SR indicated raw water; source code FN or point codes EP/FN/DS/FC indicated finished or entry/distribution water. Contradictory flags would form a separate conflict category. Other records remained unresolved. Thus “finished or entry” is a screening stratum based on available codes, not independent verification that a sample represents an individual customer’s tap water.')
    p(d,'We calculated within-point quarterly means, then averaged observed sampling points equally within system, quarter, and stage. Annual summaries averaged observed quarters equally and reported quarter counts. Missing periods remained missing. These summaries are neither flow-weighted system concentrations nor population-weighted exposure estimates. Sampling-point maxima were treated as observed maxima, whose interpretation depends on sample frequency. Censoring bounds were retained for concentrations and exceedance indicators.')
    h(d,'Table 3 Observed record availability')
    table(d,['Measure','Observed count'],[['All Iowa-filtered nitrate records','28,103'],['Distinct systems in those records','1,649'],['Community-system records before exclusions','17,017'],['Usable routine community records','17,011'],['Distinct usable community systems','845'],['Finished or entry community samples','521 across 70 systems'],['Raw community samples','1 from 1 system'],['Unresolved community samples','16,489 across 829 systems']])

    page(d);h(d,'Observed coverage results')
    p(d,'Among the 845 community systems appearing in this release, 9,866 distinct system-quarter cells contained usable routine monitoring observations, or 36.5% of the possible 27,040 cells. The median observed system-year contained one sampled quarter. Only 878 system-years had all four quarters represented; 157 of 6,760 possible system-years had no usable observation. These counts describe this release, not a census of all historical Iowa water systems. The current DNR index contains 1,082 community-system entries, but a different observation period and unknown inclusion rules prevent interpreting that cross-sectional difference as a historical missingness rate.')
    pic=d.add_picture(str(ROOT/'results/observed_data_coverage.png'),width=Inches(6.8))
    pic._inline.docPr.set('descr','Observed community nitrate sample stage and system coverage in EPA records from 2012 to 2019')
    caption(d,'Figure 1 Observed data coverage. Eligible records are routine community-system samples with numeric results or usable censoring limits. Stage is unresolved when neither source nor sampling-point codes establish it. Panel B counts systems with at least one eligible observation in each year. Source EPA Six-Year Review 4.')
    h(d,'Table 4 Annual usable monitoring coverage')
    yy=pd.read_csv(ROOT/'results/observed_yearly_description.csv')
    table(d,['Year','Samples','Systems','Stage coded samples'],[[int(r.year),f'{int(r.n_samples):,}',int(r.n_pws),int(r.n_staged)] for r in yy.itertuples()])
    p(d,'Within the original 48-system list, EPA records were available for 38 systems, totaling 2,355 usable routine samples: 2,322 unresolved, 32 finished or entry, and one raw. Ten named systems had no nitrate record in this release. Absence here does not establish that a utility failed to monitor; it may reflect purchased-water arrangements, release scope, or record availability. The 2020 Water Quality Portal query returned ambient nitrate observations without a direct PWS identifier crosswalk, so those observations were retained separately and not relabeled as public drinking-water samples.')

    page(d);h(d,'A defensible replacement causal design')
    p(d,'The primary causal question should concern the total effect of a verified construction event on nitrate in a physically connected source, with a separately specified finished-water outcome. Raw-water concentration addresses source contamination; finished-water concentration reflects contamination together with treatment, blending, and supplier responses. If demand or treatment changes are on the pathway from development to finished water, controlling for them would remove part of the total effect. They should instead be measured as mechanisms, with direct-effect questions defined separately.')
    p(d,'The unit should be an intake, wellfield, or treatment/supply system with stable identifiers and documented changes over time. Distinct customer municipalities purchasing the same produced water should not automatically count as independent exposure units. A longitudinal supplier crosswalk should record purchase shares and dates. Raw and finished samples should remain separate, and sampling-point changes should be audited. Independent source or supply-network clusters should govern uncertainty; local county and HUC clusters can be sensitivity choices when supported by the pathway.')
    p(d,'Facility ascertainment must distinguish parcel, campus, building, and project phase, retaining first land disturbance, grading completion, first withdrawal, source of cooling water, wastewater destination, and later expansions. Permit approval is a possible anticipation event, not proof of physical construction or cooling. Missing operation dates must remain unresolved rather than defining an untreated control. Source evidence should include a record identifier, document date, retrieval date, and supporting passage. Year-only dates should define timing intervals and support shifted-date sensitivity analyses.')
    p(d,'For surface-water contamination, identify the source catchment and flow path from construction parcels or permitted outfalls to the intake. For groundwater, use aquifer, depth, confinement, and capture-zone information, rather than surface watershed membership. For municipal demand, verify the facility’s actual supplier and withdrawal history. Shared HUCs and 5–20 km buffers can be exploratory proximity measures, clearly labeled as such. A city-name match cannot establish any of these pathways.')
    p(d,'The supplied replacement estimator calculates transparent paired cohort-time differences against never-treated or not-yet-treated units. For cohort g, it compares the same units at time t and baseline g minus anticipation minus one. Controls must remain unexposed through both periods plus the chosen anticipation interval. It excludes unsupported comparisons and reports cohort sizes, controls, and independent cluster counts. Event-time aggregation uses explicit treated-unit weights; a common-cohort event window should be an additional sensitivity analysis when actual support permits. This is an unadjusted group-time estimator, not a claim to implement the complete doubly robust Callaway–Sant’Anna procedure. [8]')
    p(d,'The cluster bootstrap resamples complete supply clusters and recomputes the estimator, instead of scaling another regression’s SE. It reports pointwise uncertainty and a maximum-standardized-deviation simultaneous event-study band, subject to support checks. Sparse treated clusters may require an explicitly justified case study or randomization design. Baseline balance, measured local weather, source-specific seasonality, agricultural activity, drought history, sampling intensity, and major treatment changes should be addressed before interpreting parallel trends as plausible. The pipeline currently stops short of a causal estimate because verified exposure links and measured weather were not acquired.')

    page(d);h(d,'Discussion')
    p(d,'The central failure of the original project occurs before econometric model selection: generated values are described as observed longitudinal nitrate measurements. Reproducing the reported headline estimates confirms this data-flow problem rather than the asserted environmental conclusion. Replacing the variance multipliers or choosing a modern DiD estimator would not rescue the original inference. The causal analysis must begin again with auditable measurements and exposure assignment.')
    p(d,'Public data access is not wholly blocked. EPA provided a downloadable occurrence archive, Iowa’s source-water index supported identifier verification, and a limited Water Quality Portal query returned observations. However, availability does not imply immediate fitness for the proposed causal design. Water-stage ambiguity, irregular sampling, changing source and supplier arrangements, and insufficient treatment timing can make a numerical estimate scientifically misleading. The replacement pipeline preserves these limitations rather than filling the gaps.')
    p(d,'A positive contribution of data centers to water demand is compatible with no measurable source-water nitrate effect, and a low finished-water nitrate concentration can coexist with greater treatment costs or reduced capacity. Conversely, an absence of new nitrogen production by cooling equipment does not by itself rule out effects through construction runoff, altered pumping, blending, return flows, or treatment decisions. The relative importance of these pathways requires evidence at the relevant source and supply-network scale. The present audit adjudicates none of them.')
    p(d,'Equivalence should be evaluated only after the estimand and inference are defensible. A negligible concentration difference must be justified independently of the observed estimate and should account for baseline concentration and the decision being informed. A symmetric margin for average concentration cannot automatically support equivalence for short-term maxima, exceedance probability, water availability, or treatment cost. Reporting effects with confidence intervals is more informative than declaring a flat zero.')
    h(d,'Limitations')
    p(d,'This audit concerns a single repository snapshot and does not establish the intent behind its contents. We did not independently validate all 70 facility records, their exact dates, or reported capacities. Our primary observed source ends in 2019 and contains limited stage metadata. The aggregation convention is transparent but is not a validated population exposure measure; censoring substitution remains distribution-dependent, so interval summaries are retained. A link audit checks accessibility, not the truth of all cited claims. Software tests validate selected invariants and implementation behavior, not causal identification.')
    h(d,'Conclusion')
    p(d,'The repository does not provide empirical evidence that Iowa data centers have zero or negligible effects on public-water nitrate. It also provides no valid evidence of a harmful effect. The accompanying observed-data extract, code, provenance records, and analysis gates provide a reproducible foundation for a new study once source-stage and exposure-linkage evidence are available.')
    h(d,'Data and code availability')
    p(d,'The accompanying package contains the frozen repository materials, clearly segregated generated forensic outputs, EPA Iowa raw and cleaned records, acquisition hashes, coverage tables, a standalone Colab notebook, Python scripts, and verification checks. No person-level health data were used. Author affiliations, funding, and competing-interest declarations must be supplied by the investigators before submission.')

    page(d);h(d,'References')
    refs=[
    '1. Semprini J. datacenter-nitrate-iowa repository, directory 1-gemini. Snapshot 7e1f0e6d2a3c053a47ed9d90b45e894a9e02066a. Accessed November 11, 2026. https://github.com/jsemprini/datacenter-nitrate-iowa/tree/7e1f0e6d2a3c053a47ed9d90b45e894a9e02066a/1-gemini',
    '2. US Environmental Protection Agency. Six-Year Review 4 Compliance Monitoring Data 2012–2019. PhaseChem 4 archive, SUMMARY_ANALYTE_NITRATE member. Accessed November 11, 2026. https://www.epa.gov/dwsixyearreview/six-year-review-4-compliance-monitoring-data-2012-2019',
    '3. US Environmental Protection Agency. User Guide to Downloading and Using Six-Year Review 4 Data. Dataset field descriptions and coding definitions. https://www.epa.gov/system/files/documents/2024-11/user-guide-to-downloading-and-using-syr4-data_0.pdf',
    '4. Iowa Department of Natural Resources. Source Water Protection Tracker. System index and selected SystemDetail records. Accessed November 11, 2026. https://programs.iowadnr.gov/sourcewater/',
    '5. US Environmental Protection Agency. National Primary Drinking Water Regulations. Nitrate measured as nitrogen, maximum contaminant level 10 mg/L. Accessed November 11, 2026. https://www.epa.gov/ground-water-and-drinking-water/national-primary-drinking-water-regulations',
    '6. Central Iowa Water Works. Stage III Daily Updates. Entries documenting the 2025 conservation response and nitrate-treatment constraints. Accessed November 11, 2026. https://ciww.gov/stage-iii-daily-updates/',
    '7. Meta. Meta announces new expansion to Altoona campus and new Hardhat in Hand graduates. December 2021. https://datacenters.atmeta.com/2021/12/meta-announces-new-expansion-to-altoona-campus-new-hardhat-in-hand-graduates/',
    '8. Callaway B, Sant’Anna PHC. Difference-in-Differences with multiple time periods. Journal of Econometrics. 2021;225(2):200–230. https://doi.org/10.1016/j.jeconom.2020.12.001',
    '9. Sun L, Abraham S. Estimating dynamic treatment effects in event studies with heterogeneous treatment effects. Journal of Econometrics. 2021;225(2):175–199. https://doi.org/10.1016/j.jeconom.2020.09.006',
    '10. Roth J. Pretest with caution Event-study estimates after testing for parallel trends. American Economic Review Insights. 2022;4(3):305–322. https://doi.org/10.1257/aeri.20210236',
    '11. Goodman-Bacon A. Difference-in-differences with variation in treatment timing. Journal of Econometrics. 2021;225(2):254–277. https://doi.org/10.1016/j.jeconom.2021.03.014',
    '12. USGS and US Environmental Protection Agency. Water Quality Portal. Iowa nitrate result query, collection year 2020. Ambient results retained separately from PWS compliance records. Accessed November 11, 2026. https://www.waterqualitydata.us/'
    ]
    for x in refs:p(d,x)
    d.save(OUT/'Iowa_Data_Centers_Nitrate_Manuscript.docx')

def brief():
    d=document('Calibri',11)
    title(d,'What the Iowa data center nitrate study can establish','Research brief')
    h(d,'The reported zero effect is unsupported')
    p(d,'The study’s nitrate outcomes and weather controls were generated in code, then described as historical water records. Re-executing the scripts reproduced the headline estimates. It did not verify a real-world finding that data centers have no effect on nitrate.')
    h(d,'What the audit found')
    bullet(d,'All 4,176 quarterly nitrate observations were constructed from assumed baselines, seasonal patterns, selected overrides, and random noise. The code did not analyze downloaded nitrate measurements.')
    bullet(d,'A deliberately extreme input nitrate record left the output unchanged because the purported raw-file ingestion path never read the file.')
    bullet(d,'The claimed group-time uncertainty was created by multiplying another model’s standard errors. Several spatial counts and staggered estimates did not match the written report.')
    bullet(d,'All 48 water-system IDs matched Iowa’s public index. That successful check validates system identities, not the nitrate measurements or facility-to-water-source links.')
    h(d,'Table 1 The headline calculations')
    table(d,['Generated-data estimate','Reported change'],[['Construction within 10 km','+0.0013 mg/L as N'],['Operation within 10 km','−0.0124 mg/L as N']])
    caption(d,'These calculations reproduce from generated data. They are not estimates of actual changes in Iowa drinking water.')
    h(d,'What this means for policy')
    p(d,'This project establishes neither harm nor absence of harm from data centers. Its zero-effect, equivalence, and weather-attribution claims should be removed from public communications. Water demand, treatment capacity, raw-water contamination, and finished-water concentration are separate outcomes that require separate evidence.')
    p(d,'Nitrate-treatment constraints during the 2025 Central Iowa Water Works conservation response are documented by the utility. That context does not establish which industries or land uses caused the measured nitrate concentrations.')
    caption(d,'Sources Repository snapshot 7e1f0e6; original manuscript and Python scripts; Iowa DNR Source Water Protection Tracker; Central Iowa Water Works Stage III Daily Updates. Detailed evidence and executable checks are in the accompanying peer review and code package.')

    page(d);h(d,'Actual public records provide a starting point')
    p(d,'The replacement workflow downloaded EPA nitrate records for 2012–2019 and preserved observed values, sample-specific detection limits, missing periods, and unresolved water-stage labels.')
    table(d,['Available observed data','Coverage'],[['Iowa nitrate records','28,103'],['Usable routine community samples','17,011 from 845 systems'],['Unresolved raw or finished stage','16,489 samples or 96.9%'],['Finished or entry stage','521 samples from 70 systems'],['Usable system-quarter coverage','9,866 of 27,040 cells or 36.5%'],['Original 48 systems present in EPA release','38 systems with 2,355 usable samples']])
    caption(d,'System-quarter denominator is limited to community systems appearing in the EPA release. Missing records do not establish a utility’s failure to monitor. These data end in 2019 and cannot test claims about 2025–2026.')
    h(d,'What a credible follow up requires')
    bullet(d,'Obtain dated raw and finished nitrate samples, sampling locations, method-specific reporting limits, and treatment or supplier changes through the study end date.')
    bullet(d,'Verify actual land-disturbance and cooling-withdrawal dates, separately for campuses and expansions. Approval dates and planned projects cannot substitute for operation.')
    bullet(d,'Connect facilities to real intake catchments, groundwater capture zones, or municipal suppliers. City names and distance alone are insufficient.')
    bullet(d,'Use comparable unexposed water sources, measured weather, and enough independent treated supply systems for credible inference. Preserve unobserved periods and report sensitivity to censoring and sampling intensity.')
    h(d,'What has been delivered')
    p(d,'The package includes the repository snapshot, forensic replication outputs clearly marked as generated, the observed EPA extract, scripts for extraction and cleaning, coverage analyses, a Colab notebook, verification checks, a fresh manuscript, and an independent peer-review report. The causal-analysis path stops until reviewed exposure and source links are supplied.')
    caption(d,'Primary data EPA Six-Year Review 4 Compliance Monitoring Data 2012–2019 and its user guide. https://www.epa.gov/dwsixyearreview/six-year-review-4-compliance-monitoring-data-2012-2019')
    d.save(OUT/'Iowa_Data_Centers_Nitrate_Brief.docx')

def peer_review():
    d=document('Calibri',11)
    title(d,'Peer review of the Iowa data center nitrate study','Independent methodological and computational assessment')
    h(d,'Recommendation')
    p(d,'Reject in its current empirical form. The principal outcome and weather variables are generated by the supplied code rather than obtained from observed water records. This is a foundational data-provenance failure that prevents interpretation of the reported causal effects, equivalence tests, and mechanism results. A corrected empirical paper requires rebuilding the dataset and re-estimating the analysis; editing the prose or replacing one estimator is insufficient.')
    h(d,'Scope and successful checks')
    p(d,'I reviewed the 17-page manuscript, accompanying media article, report, prompt and framing materials, 70-row facility inventory, and both Python scripts at commit 7e1f0e6d2a3c053a47ed9d90b45e894a9e02066a. I re-executed the code in an isolated output directory and independently retrieved EPA nitrate records. This assessment concerns the verifiable behavior of those materials and does not infer the intent of their author or generator.')
    p(d,'The research question is relevant, and the proposed distinction between construction, operation, source water, and finished water could support a useful study. All 48 PWS identifiers match Iowa’s public index. The facility CSV reproduces from the code, and the headline TWFE estimates reproduce to reported precision. Of 50 unique URLs embedded in the manuscript, 47 returned HTTP 200 and three returned HTTP 403 in this session. Link accessibility does not establish that an underlying source supports every cited numerical claim.')
    h(d,'Major concern 1 Generated outcomes are presented as measurements')
    p(d,'In 01_fetch_and_clean_data.py, build_pws_nitrate_panels starts a fixed random generator near line 609, assigns assumed weather values near lines 611–635, and computes nitrate from manually supplied system baselines, seasonal amplitudes, source sensitivities, and random noise near lines 647–714. Selected system-year overrides appear near lines 716–725. The code contains no parser that turns returned Water Quality Portal observations into the reported panel.')
    p(d,'The external-file path only checks existence and logs “ingesting directly.” A challenge file containing an extreme nitrate value did not alter any quarterly outcome: the panel hash was identical. The manuscript nevertheless describes a balanced observed monitoring panel on pages 1 and 6–7, and the media article presents the resulting estimates as an actual statewide finding.')
    p(d,'Required remedy  Remove all empirical effect and equivalence claims based on these values. Supply the raw downloaded records, metadata, extraction logs, sample-level cleaning code, and traceable joins from samples to analysis rows. The 912-row generated sample preview cannot serve as the underlying measurement archive.')

    page(d);h(d,'Major concern 2 Uncertainty and estimator labels are invalid')
    p(d,'In 02_did_equivalence_analysis.py, run_stacked_and_cs_did sets se_cs = se_stk * 1.04 and se_overall_cs = se_overall_stk * 1.03. These are not variance estimates for the cohort-time ATT. The same routine substitutes a stacked coefficient when a cohort-time estimate is missing. Pointwise intervals and equivalence tests based on these quantities have no justified sampling interpretation.')
    p(d,'The cohort-time calculation residualizes outcomes using a pooled regression among never-treated observations. It is not shown to implement the conditional-parallel-trends estimator or its influence function described by Callaway and Sant’Anna. The stacked regression is labeled interchangeably as Sun–Abraham and stacked DiD, although the interaction-weighted estimator is not implemented. The routine also excludes the 2006 and 2007 treated cohorts without substantive justification.')
    p(d,'Required remedy  Describe the estimator actually used. Estimate cohort-time effects and their covariance using a validated implementation or a transparent paired-change estimator with a supply-cluster bootstrap that recomputes all stages. Report support and weights for each event time. Do not borrow uncertainty from a different estimator or replace missing event times with another method’s result.')
    h(d,'Major concern 3 Exposure definitions do not establish the pathways')
    p(d,'The “same municipality” rule matches city strings rather than verified service boundaries. Distance buffers use hard-coded PWS coordinates with no demonstrated intake location accuracy. The hydrologic rule uses a manually supplied HUC10 lookup list. A shared watershed code is not proof of upstream connectivity, and surface watersheds do not establish groundwater transport to a deep well.')
    p(d,'Purchased-water municipalities can share source concentrations and treatment decisions even when their local watersheds differ. That network can contaminate the treatment/control contrast and create dependence across county or HUC clusters. The manuscript does not establish which data centers buy water from which suppliers or where cooling return flows enter a receiving water.')
    p(d,'Required remedy  Provide a dated facility-to-source and facility-to-supplier crosswalk with documentary evidence. Separate a source-contamination estimand from a demand-mediated finished-water estimand. Use intake catchments and flow direction for surface water; aquifer and capture zones for groundwater; and observed purchase/withdrawal arrangements for demand. Treat proximity as exploratory if stronger links cannot be established.')
    h(d,'Major concern 4 Timing and cumulative exposure are misclassified')
    p(d,'Quarterly treatment indicators are based on calendar year even when quarter dates exist. This assigns treatment before a late-year construction or activation event. Mechanism variables assign all matched site acreage or power at the earliest event, incorporating future expansions into earlier exposures. Construction and operation are modeled separately without establishing how ongoing construction effects are distinguished from activation effects.')
    p(d,'Required remedy  Use verified lifecycle dates at their actual precision; carry interval uncertainty where necessary. Define campuses and expansions consistently. Distinguish approval, disturbance, first withdrawal, and later intensity changes. Reframe operation estimates as post-activation associations unless the design identifies an incremental operation effect beyond construction.')

    page(d);h(d,'Major concern 5 The written results are not fully reproducible')
    table(d,['Quantity','Written material','Reexecution'],[['Construction TWFE','+0.0013','+0.00129'],['Operation TWFE','−0.0124','−0.01238'],['Group time overall ATT','−0.0212','−0.01627'],['Stacked static ATT in report','+0.0018','−0.00747'],['Treated systems within 10 km','21','31'],['Treated same municipality','15','19']])
    caption(d,'Effect units are mg/L as N. The first two values reproduce to the displayed precision; the others require reconciliation. All effect results here are generated-data forensic outputs. The complete comparison tables accompany this review.')
    p(d,'The facility CSV also sums to 6,606.5 MW across 20 county names, whereas the narrative describes 6,200.5 deduplicated MW and 18 counties. A deduplicated total could be defensible, but its campus/phase rules and transformation are not implemented or documented in the supplied output. Permitting effects are asserted in the abstract even though the supplied model specification list does not estimate a permitting treatment.')
    p(d,'Required remedy  Generate manuscript tables directly from analysis outputs, document every sample restriction, and reconcile project-level counts and capacities. Do not claim statewide completeness from a tracker headline count alone. Independently verify individual facility records and exact dates; generic tracker URLs do not validate all row-level fields.')
    h(d,'Major concern 6 Equivalence and pretrend claims are overstated')
    p(d,'Even on observed data, a TOST result would support equivalence only for a specified estimand, margin, and uncertainty model. It would not prove the null hypothesis beta = 0. The 0.25 mg/L margin is not justified beyond being a fraction of the regulatory limit. The same numeric margin is passed to the binary exceedance model, where it means 25 percentage points. The 0.05 SD margin depends on the generated outcome distribution.')
    p(d,'The code sets pre_trends_parallel_confirmed to true when a pretrend p value exceeds 0.10. A low-powered failure to reject cannot confirm parallel trends. The reported post hoc MDE is a standard-error-based approximation and does not demonstrate the power of a realistic irregular monitoring design with shared suppliers and few treated clusters.')
    p(d,'Required remedy  Specify outcome-specific margins independently of the result; report concentration and probability effects in their correct units. Show event-time support, simultaneous uncertainty, and sensitivity to plausible trend deviations. Plan power using observed variance, missingness, temporal dependence, and the number of independent exposed source/supply clusters. Present nonsignificant pretrends as inconclusive diagnostics.')

    page(d);h(d,'Major concern 7 The mechanism and public claims exceed the evidence')
    p(d,'The precipitation and temperature coefficients are generated by construction of the outcome, not estimates using measured weather. The manuscript cannot use them to conclude that agricultural flushing rather than data centers caused the 2025–2026 crises. The media article’s “flat zero,” assertion that construction removes nitrogen, and attribution of more than 95% of nitrate to upstream agriculture require evidence separate from this pipeline.')
    p(d,'Cooling’s lack of direct nitrogen production does not exclude effects through construction, altered pumping or blending, withdrawal-induced flow changes, or downstream return flows. Conversely, water demand and nitrate concentration are distinct outcomes. A nitrate-equivalence result would not establish equivalence of treatment costs, capacity, or availability.')
    p(d,'Required remedy  Remove causal mechanism and policy-exoneration language unless supported by independent analyses. Use a neutral policy brief that distinguishes known facts, the unresolved question, and required evidence. Avoid treating nitrate below the MCL as proof of no exposure concern or a short-term null as evidence about cancer outcomes.')
    h(d,'What the independent data retrieval establishes')
    p(d,'EPA’s public Six-Year Review 4 archive was downloadable in this session. It contains 28,103 Iowa-filtered nitrate records for 2012–2019. Restricting to usable routine community samples leaves 17,011 records from 845 systems. Source-stage metadata are unresolved for 96.9% of those records; only 521 are classified as finished or entry and one as raw using the available codes. These data cannot simply replace the purported balanced 2005–2026 panel. Among the original 48 systems, 38 have records in this release; absence of a record does not demonstrate absence of monitoring.')
    p(d,'I retained unknown stages, sample-specific censoring intervals, and missing quarters. The replacement pipeline produces descriptive coverage results and refuses causal estimation without a reviewed exposure crosswalk. This is the appropriate stopping point for the currently verified inputs, while targeted data acquisition continues through the supplied code and request specification.')
    h(d,'Presentation and reproducibility revisions')
    bullet(d,'Replace the unsupported institutional byline and all author or preprint placeholders with verified author information before submission or dissemination.')
    bullet(d,'Separate raw, entry, and distribution-water observations; report the sampling unit, weighting convention, censoring burden, and points per system-period.')
    bullet(d,'Explain whether maxima are sample maxima or measured continuous peaks, and assess sampling-frequency sensitivity.')
    bullet(d,'Distinguish an observed HTTP or form error from an assumed CAPTCHA or an inability to obtain any data. Retain failed attempts in an acquisition log.')
    bullet(d,'Keep generated demonstration outputs visibly segregated from observed records. Release hashes, executable code, data dictionaries, and machine-generated result tables.')
    h(d,'Overall assessment')
    p(d,'The question merits a new study. The submitted empirical conclusion is not supported by the supplied project. Rebuilding from observed data and verified source connections is necessary before either a harmful-effect or negligible-effect conclusion can be evaluated.')
    d.save(OUT/'Iowa_Data_Centers_Nitrate_Peer_Review.docx')

if __name__=='__main__':manuscript();brief();peer_review()
