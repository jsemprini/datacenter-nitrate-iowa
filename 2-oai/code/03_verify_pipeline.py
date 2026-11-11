"""Scientific checks for censoring, stage mixing, paired DiD and design gates.

Small artificial fixtures below are software tests, never water observations.
Run: python code/03_verify_pipeline.py
"""
import importlib.util
import unittest
from pathlib import Path
import numpy as np
import pandas as pd

HERE=Path(__file__).resolve().parent
def module(name):
    s=importlib.util.spec_from_file_location('m'+name,HERE/(name+'.py'))
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
clean=module('01_clean_data');analysis=module('02_analyze_data')

class ScientificChecks(unittest.TestCase):
    def fixture(self):
        return pd.DataFrame([
          {'SIX_YEAR_ID':'1','PWSID':'IA0000001','ANALYTE_CODE':'1040','SAMPLE_COLLECTION_DATE':'01-JAN-12',
           'VALUE':'2500','UNIT':'UG/L','DETECT':'1','DETECTION_LIMIT_VALUE':'0.1','DETECTION_LIMIT_UNIT':'MG/L',
           'SYSTEM_TYPE':'C','SAMPLE_TYPE_CODE':'RT','SOURCE_TYPE_CODE':'FN','SAMPLING_POINT_TYPE':'EP',
           'SAMPLING_POINT_ID':'a','WATER_FACILITY_ID':'z'},
          {'SIX_YEAR_ID':'2','PWSID':'IA0000001','ANALYTE_CODE':'1040','SAMPLE_COLLECTION_DATE':'01-APR-12',
           'VALUE':'','UNIT':'','DETECT':'0','DETECTION_LIMIT_VALUE':'100','DETECTION_LIMIT_UNIT':'UG/L',
           'SYSTEM_TYPE':'C','SAMPLE_TYPE_CODE':'RT','SOURCE_TYPE_CODE':'','SAMPLING_POINT_TYPE':'',
           'SAMPLING_POINT_ID':'a','WATER_FACILITY_ID':'z'}])

    def test_units_and_sample_specific_limits(self):
        x=clean.clean_samples(self.fixture())
        self.assertAlmostEqual(x.iloc[0].nitrate_mid,2.5)
        self.assertAlmostEqual(x.iloc[1].nitrate_upper,.1)
        self.assertAlmostEqual(x.iloc[1].nitrate_mid,.1/np.sqrt(2))
        self.assertEqual(x.iloc[1].stage,'unresolved')

    def test_stage_conflict_is_not_finished(self):
        self.assertEqual(clean.classify_stage({'SOURCE_TYPE_CODE':'RW','SAMPLING_POINT_TYPE':'EP'}),'conflict')

    def test_missing_quarters_are_not_created(self):
        q,a=clean.aggregate(clean.clean_samples(self.fixture()))
        self.assertEqual(len(q),2)
        self.assertEqual(a.n_quarters.max(),1)  # separate stage strata
        self.assertEqual(set(q.stage),{'finished_or_entry','unresolved'})

    def test_conflicting_duplicate_id_fails(self):
        x=self.fixture();x.loc[1,'SIX_YEAR_ID']='1'
        with self.assertRaises(ValueError):clean.clean_samples(x)

    def test_paired_changes_avoid_composition_bias(self):
        # A high-level control observed only at follow-up must not enter a paired change.
        d=pd.DataFrame({'pwsid':['T','C','M'],'g':[2014*4,np.inf,np.inf],'cluster_id':['t','c','m']})
        rows=[]
        for u,level in [('T',3),('C',10),('M',1000)]:
            for t in range(2012*4,2015*4):
                if u=='M' and t<2014*4:continue
                y=level+0.2*(t-2012*4)+(2 if u=='T' and t>=2014*4 else 0)
                rows.append({'pwsid':u,'quarter_index':t,'nitrate_mid':y})
        cells=analysis.group_time_cells(pd.DataFrame(rows),d,window=(0,1),min_pre=4)
        np.testing.assert_allclose(cells.att,2,atol=1e-12)
        self.assertTrue(cells.n_controls.eq(1).all())

    def test_unknown_exposure_is_not_a_control(self):
        d=pd.DataFrame([{'pwsid':'x','phase':'construction','status':'unresolved','event_date':'',
                         'verified':True,'cluster_id':'x','exposure_definition':'source',
                         'evidence_url':'https://example.org','ascertained_through':'2019-12-31'}])
        with self.assertRaises(ValueError):analysis.validate_design(d,'construction','2019-12-31')

    def test_equivalence_is_not_non_significance(self):
        self.assertFalse(analysis.tost_from_estimate(0,1,20,.25)['equivalent'])
        self.assertTrue(analysis.tost_from_estimate(0,.01,20,.25)['equivalent'])

    def test_real_bootstrap_has_nonzero_uncertainty(self):
        # Synthetic fixture with known nonzero effect and enough independent clusters.
        rng=np.random.default_rng(981);rows=[];design=[];g=2014*4
        for i in range(24):
            u=f'u{i}';design.append({'pwsid':u,'g':g if i<12 else np.inf,'cluster_id':f'supply{i}'})
            for t in range(2012*4,2016*4):
                rows.append({'pwsid':u,'quarter_index':t,'nitrate_mid':i+.03*t+rng.normal(0,.3)+(1 if i<12 and t>=g else 0)})
        cells,events=analysis.bootstrap_dynamic(pd.DataFrame(rows),pd.DataFrame(design),B=99,window=(0,2))
        self.assertTrue(events.se_bootstrap.gt(0).all())
        self.assertTrue(events.att.between(.5,1.5).all())
        self.assertTrue((events.band95_high>=events.ci95_high).all())

if __name__=='__main__':unittest.main(verbosity=2)
