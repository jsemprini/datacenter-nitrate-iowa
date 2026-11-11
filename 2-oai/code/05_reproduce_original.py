"""Forensic execution only. All generated nitrate and weather outputs are synthetic."""
import importlib.util, pathlib, json, hashlib, contextlib, io
import pandas as pd
ROOT=pathlib.Path(__file__).resolve().parents[1]
OUT=ROOT/'forensic_reproduction'/'SYNTHETIC_OUTPUTS';OUT.mkdir(parents=True,exist_ok=True)
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
m=load('original_ingest',ROOT/'source_original'/'01_fetch_and_clean_data.py')
m.OUTPUT_DIR=str(OUT);m.WORKSPACE_ROOT=str(OUT)
m.try_fetch_url=lambda *args,**kwargs:''
d=m.build_iowa_data_centers_panel();p=m.build_iowa_pws_metadata();l=m.link_pws_to_data_centers(p,d)
s,q,a=m.build_pws_nitrate_panels(l,d)
for f,df in [('facilities',d),('pws_metadata',p),('linked_metadata',l),('SYNTHETIC_samples',s),('iowa_pws_nitrate_panel_quarterly',q),('iowa_pws_nitrate_panel_annual',a)]:df.to_csv(OUT/(f+'.csv'),index=False)
original=pd.read_csv(ROOT/'source_original'/'iowa_data_centers_panel.csv')
(OUT/'raw_iowa_dnr_sdwis_nitrate.csv').write_text('PWSID,Concentration_mg_L\nIA7727031,987654.321\n')
s2,q2,a2=m.build_pws_nitrate_panels(l,d)
(OUT/'raw_iowa_dnr_sdwis_nitrate.csv').unlink()
def digest(df):return hashlib.sha256(df.to_csv(index=False).encode()).hexdigest()
summary={'data_class':'SYNTHETIC FORENSIC REPRODUCTION NOT OBSERVED WATER DATA','n_facility_rows':len(d),'facility_csv_matches':pd.read_csv(OUT/'facilities.csv').equals(original), 'n_pws':len(p),'n_quarter_rows':len(q),'n_annual_rows':len(a),'n_sample_preview_rows':len(s),'n_quarters':q.year_quarter.nunique(),'n_counties':q.county.nunique(),'n_huc10':q.huc10.nunique(),'n_treated_pws_10km':l.cohort_construct_10km.notna().sum().item(),'drop_file_changes_output':digest(q)!=digest(q2),'quarter_sha256':digest(q),'treated_construction_cohorts':l.groupby('cohort_construct_10km').size().to_dict()}
(OUT/'reproduction_checks.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
n=load('original_analysis',ROOT/'source_original'/'02_did_equivalence_analysis.py');n.OUTPUT_DIR=str(OUT);n.WORKSPACE_ROOT=str(OUT);n.main()
