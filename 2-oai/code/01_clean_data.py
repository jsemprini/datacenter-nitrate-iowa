"""Preserve sample provenance, censoring intervals, and unresolved water stage.

EPA analyte 1040 is regulatory nitrate reported as nitrogen. Result units and
detection-limit units are converted independently. No common MDL is invented.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd

def unit_factor(unit):
    return {'UG/L':0.001,'MG/L':1.0}.get(str(unit).strip().upper(),np.nan)

def classify_stage(row):
    source=str(row.get('SOURCE_TYPE_CODE','')).upper()
    point=str(row.get('SAMPLING_POINT_TYPE','')).upper()
    # Contradictory flags are never resolved by simply preferring one source.
    raw=source=='RW' or point in {'RW','SR'}
    finished=source=='FN' or point in {'EP','FN','DS','FC'}
    if raw and finished:return 'conflict'
    if raw:return 'raw'
    if finished:return 'finished_or_entry'
    return 'unresolved'

def clean_samples(raw):
    x=raw.copy()
    required={'SIX_YEAR_ID','PWSID','ANALYTE_CODE','SAMPLE_COLLECTION_DATE','VALUE','UNIT',
              'DETECT','DETECTION_LIMIT_VALUE','DETECTION_LIMIT_UNIT','SYSTEM_TYPE','SAMPLE_TYPE_CODE'}
    if required-set(x):raise ValueError('Missing fields: '+str(sorted(required-set(x))))
    if not x.ANALYTE_CODE.astype(str).eq('1040').all():raise ValueError('Nitrate-only file required')
    # An exact repeated release row may be removed. Conflicting analytical IDs are fatal.
    x=x.drop_duplicates().copy()
    if x.SIX_YEAR_ID.duplicated().any():raise ValueError('Conflicting duplicate SIX_YEAR_ID values')
    x['pwsid']=x.PWSID.astype(str).str.upper()
    # The state-filtered EPA release also includes federally administered tribal IDs.
    if not x.pwsid.str.fullmatch(r'(?:IA\d{7}|\d{9})').all():raise ValueError('Unexpected PWS identifier format')
    x['date']=pd.to_datetime(x.SAMPLE_COLLECTION_DATE,format='%d-%b-%y',errors='coerce')
    if x.date.isna().any():raise ValueError('Unparseable collection dates')
    if not x.date.between('2012-01-01','2019-12-31').all():raise ValueError('Dates outside SYR4 release')
    x['year']=x.date.dt.year;x['period']=x.date.dt.to_period('Q').astype(str)
    x['quarter_index']=x.date.dt.year*4+x.date.dt.quarter-1
    x['stage']=x.apply(classify_stage,axis=1)
    result=pd.to_numeric(x.VALUE,errors='coerce')*x.UNIT.map(unit_factor)
    limit=pd.to_numeric(x.DETECTION_LIMIT_VALUE,errors='coerce')*x.DETECTION_LIMIT_UNIT.map(unit_factor)
    x['censored']=x.DETECT.astype(str).eq('0')
    detected=x.DETECT.astype(str).eq('1')
    valid_det=detected & result.ge(0)
    valid_nd=x.censored & limit.gt(0)
    x['nitrate_lower']=np.where(valid_det,result,np.where(valid_nd,0,np.nan))
    x['nitrate_upper']=np.where(valid_det,result,np.where(valid_nd,limit,np.nan))
    x['nitrate_mid']=np.where(valid_det,result,np.where(valid_nd,limit/np.sqrt(2),np.nan))
    x['limit_mg_l_as_n']=limit
    x['eligible']=x.SYSTEM_TYPE.eq('C') & x.SAMPLE_TYPE_CODE.eq('RT') & x.nitrate_mid.notna()
    x['data_class']='observed_epa_syr4'
    return x

def aggregate(samples,frequency='quarter'):
    """Equal sampling-point weights, then equal observed quarter weights annually.

    Missing quarters are retained only in the coverage grid and never filled.
    Stage strata remain separate. No point is treated as a population weight.
    """
    x=samples.loc[samples.eligible].copy()
    x['point']=x.SAMPLING_POINT_ID.fillna('').replace('', 'UNKNOWN_POINT')
    x['facility']=x.WATER_FACILITY_ID.fillna('').replace('', 'UNKNOWN_FACILITY')
    keys=['pwsid','stage','year','period','quarter_index']
    point=(x.groupby(keys+['facility','point'],dropna=False)
           .agg(nitrate_mid=('nitrate_mid','mean'),nitrate_lower=('nitrate_lower','mean'),
                nitrate_upper=('nitrate_upper','mean'),n_samples=('SIX_YEAR_ID','size'),
                observed_max=('nitrate_upper','max'),censored_share=('censored','mean')).reset_index())
    q=(point.groupby(keys,dropna=False)
       .agg(nitrate_mid=('nitrate_mid','mean'),nitrate_lower=('nitrate_lower','mean'),
            nitrate_upper=('nitrate_upper','mean'),n_samples=('n_samples','sum'),n_points=('point','size'),
            observed_max=('observed_max','max'),censored_share=('censored_share','mean')).reset_index())
    # Exceedance interval: unknown if a non-detect has an upper bound above 5.
    peaks=x.groupby(keys).agg(max_lower=('nitrate_lower','max'),max_upper=('nitrate_upper','max')).reset_index()
    q=q.merge(peaks,on=keys,validate='one_to_one')
    q['exceed5_lower']=(q.max_lower>5).astype(int)
    q['exceed5_upper']=(q.max_upper>5).astype(int)
    q['data_class']='observed_epa_syr4'
    a=(q.groupby(['pwsid','stage','year'])
       .agg(nitrate_mid=('nitrate_mid','mean'),nitrate_lower=('nitrate_lower','mean'),
            nitrate_upper=('nitrate_upper','mean'),n_samples=('n_samples','sum'),n_quarters=('period','nunique'),
            observed_max=('observed_max','max')).reset_index())
    a['data_class']='observed_epa_syr4'
    return q,a

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.');args=ap.parse_args()
    root=Path(args.root);data=root/'data';out=data/'clean';out.mkdir(parents=True,exist_ok=True)
    x=clean_samples(pd.read_csv(data/'raw/epa_syr4_iowa_nitrate_raw.csv',dtype=str))
    x.to_csv(out/'nitrate_samples.csv',index=False)
    q,a=aggregate(x);q.to_csv(out/'nitrate_quarterly.csv',index=False);a.to_csv(out/'nitrate_annual.csv',index=False)
    # Coverage counts at the unit-year level across all stages, without duplicating PWS-years.
    obs=(x.loc[x.eligible].groupby(['pwsid','year'])
         .agg(n_samples=('SIX_YEAR_ID','size'),n_quarters=('period','nunique')).reset_index())
    ids=sorted(x.loc[x.SYSTEM_TYPE.eq('C'),'pwsid'].unique())
    grid=pd.MultiIndex.from_product([ids,range(2012,2020)],names=['pwsid','year']).to_frame(index=False)
    grid=grid.merge(obs,how='left',on=['pwsid','year'],validate='one_to_one')
    grid['observed']=grid.n_samples.notna();grid.to_csv(out/'coverage_grid.csv',index=False)
    summary={'raw_iowa_rows':len(x),'all_pws':x.pwsid.nunique(),'community_rows':int(x.SYSTEM_TYPE.eq('C').sum()),
             'community_pws':len(ids),'eligible_rows':int(x.eligible.sum()),
             'eligible_pws':x.loc[x.eligible,'pwsid'].nunique(),
             'stage_all_rows':x.stage.value_counts().to_dict(),
             'stage_community_rows':x.loc[x.SYSTEM_TYPE.eq('C'),'stage'].value_counts().to_dict(),
             'stage_eligible_rows':x.loc[x.eligible,'stage'].value_counts().to_dict(),
             'censored_rows':int(x.censored.sum()),'unusable_numeric_rows':int(x.nitrate_mid.isna().sum()),
             'unobserved_community_pws_years':int((~grid.observed).sum()),
             'community_pws_year_grid':len(grid),'quarterly_stratum_rows':len(q),
             'annual_stratum_rows':len(a)}
    (out/'cleaning_summary.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2))

if __name__=='__main__':main()
