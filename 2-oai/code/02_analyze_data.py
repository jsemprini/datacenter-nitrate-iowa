"""Observed-data description and a gated, paired group-time DiD estimator.

No data-center effects are estimated without a reviewed exposure crosswalk.
The optional estimator is transparent unadjusted group-time DiD, not advertised
as a full implementation of the Callaway-Sant'Anna doubly robust estimator.
"""
from __future__ import annotations
import argparse, json
from pathlib import Path
import numpy as np
import pandas as pd
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def validate_design(design,phase,cutoff):
    required={'pwsid','phase','status','event_date','verified','cluster_id','exposure_definition','evidence_url','ascertained_through'}
    if required-set(design):raise ValueError('Missing crosswalk columns: '+str(sorted(required-set(design))))
    d=design.loc[design.phase.eq(phase)].copy()
    if d.empty:raise ValueError('No reviewed design for requested phase')
    if d.pwsid.duplicated().any():raise ValueError('One first-event record per PWS and phase required')
    approved=d.verified.astype(str).str.lower().isin(['true','1'])
    if not approved.all():raise ValueError('Unverified crosswalk rows; do not infer controls from blanks')
    if not d.status.isin(['treated','never_by_cutoff']).all():raise ValueError('Unresolved exposure status')
    if d[['cluster_id','exposure_definition','evidence_url']].isna().any().any():raise ValueError('Missing exposure or supply-network evidence')
    d['date']=pd.to_datetime(d.event_date,errors='coerce')
    ascertain=pd.to_datetime(d.ascertained_through,errors='coerce')
    if (ascertain.isna() | ascertain.lt(pd.Timestamp(cutoff))).any():raise ValueError('Exposure ascertainment does not cover analysis cutoff')
    if (d.status.eq('treated') & d.date.isna()).any():raise ValueError('Treated event date missing')
    if (d.status.eq('never_by_cutoff') & d.date.notna()).any():raise ValueError('Control with event date')
    d['g']=np.where(d.status.eq('treated'), d.date.dt.year*4+d.date.dt.quarter-1,np.inf)
    return d

def group_time_cells(panel,design,window=(-8,12),anticipation=0,min_pre=4):
    """Paired changes with fixed g-anticipation-1 baseline and clean controls.

    Count units separately for every comparison. Require observed baseline and
    follow-up for the same units, rather than subtracting changing sample means.
    Equal cohort-unit weights aggregate cells at each event time. Outcomes must
    contain one stage and one row per PWS-quarter.
    """
    if panel.duplicated(['pwsid','quarter_index']).any():raise ValueError('Duplicate unit-period observations')
    p=panel[['pwsid','quarter_index','nitrate_mid']].dropna()
    wide=p.pivot(index='pwsid',columns='quarter_index',values='nitrate_mid')
    d=design.set_index('pwsid').loc[lambda z:z.index.isin(wide.index)].copy()
    wide=wide.loc[d.index]
    rows=[]
    for g in sorted(d.loc[np.isfinite(d.g),'g'].unique()):
        base=int(g)-anticipation-1
        if base not in wide:continue
        precols=[c for c in wide if c<int(g)-anticipation]
        preok=wide[precols].notna().sum(axis=1).ge(min_pre)
        for k in range(window[0],window[1]+1):
            t=int(g)+k
            if t==base or t not in wide:continue
            diff=wide[t]-wide[base]
            paired=diff.notna() & preok
            tr=d.g.eq(g) & paired
            # For pre-event placebo contrasts, exclude the target cohort as controls.
            co=(d.g>max(t,base)+anticipation) & ~d.g.eq(g) & paired
            if tr.sum()==0 or co.sum()==0:continue
            rows.append({'g':int(g),'t':t,'k':k,'att':float(diff[tr].mean()-diff[co].mean()),
                         'n_treated':int(tr.sum()),'n_controls':int(co.sum()),
                         'treated_clusters':d.loc[tr,'cluster_id'].nunique(),
                         'control_clusters':d.loc[co,'cluster_id'].nunique()})
    return pd.DataFrame(rows)

def dynamic_aggregate(cells):
    if cells.empty:return pd.Series(dtype=float)
    return cells.groupby('k').apply(lambda z:np.average(z.att,weights=z.n_treated),include_groups=False)

def bootstrap_dynamic(panel,design,B=999,seed=20261111,**kwargs):
    """Resample physical supply clusters and recompute the complete estimator.

    Refuse to report intervals if any event time has too few valid draws. Rare
    treated clusters can make inference infeasible even when sample N is large.
    Bands use the maximum standardized bootstrap deviation across event times.
    """
    cells=group_time_cells(panel,design,**kwargs);theta=dynamic_aggregate(cells)
    if theta.empty:raise ValueError('No paired group-time support')
    groups=design.cluster_id.dropna().unique()
    if len(groups)<10:raise ValueError('Fewer than 10 supply clusters; use a case-study/randomization design with explicit assumptions')
    rng=np.random.default_rng(seed);draws=[]
    for b in range(B):
        pp=[];dd=[]
        for j,group in enumerate(rng.choice(groups,len(groups),replace=True)):
            part=design.loc[design.cluster_id.eq(group)].copy()
            mapping={i:f'{i}__draw{j}' for i in part.pwsid}
            p=panel.loc[panel.pwsid.isin(mapping)].copy();p['pwsid']=p.pwsid.map(mapping)
            part['pwsid']=part.pwsid.map(mapping);part['cluster_id']=str(j)
            pp.append(p);dd.append(part)
        cc=group_time_cells(pd.concat(pp,ignore_index=True),pd.concat(dd,ignore_index=True),**kwargs)
        draws.append(dynamic_aggregate(cc).reindex(theta.index))
    boot=pd.DataFrame(draws)
    fraction=boot.notna().mean()
    if (fraction<0.95).any():raise ValueError('Insufficient valid bootstrap draws at some event times; narrow support or change design')
    complete=boot.dropna()
    if len(complete)<0.90*B:raise ValueError('Insufficient joint event-window bootstrap support')
    se=complete.std(ddof=1)
    if (se<=0).any():raise ValueError('Degenerate bootstrap uncertainty')
    deviation=complete-theta
    c95=float((deviation.abs()/se).max(axis=1).quantile(.95))
    out=pd.DataFrame({'k':theta.index,'att':theta.values,'se_bootstrap':se.values,
                      'ci95_low':theta.values+deviation.quantile(.025).values,
                      'ci95_high':theta.values+deviation.quantile(.975).values,
                      'band95_low':theta.values-c95*se.values,'band95_high':theta.values+c95*se.values,
                      'valid_draw_fraction':fraction.values})
    return cells,out

def tost_from_estimate(beta,se,df,delta):
    """Only for a valid estimator with an independently justified margin."""
    if not (se>0 and df>0 and delta>0):raise ValueError('Positive SE, degrees of freedom and margin required')
    p=max(stats.t.sf((beta+delta)/se,df),stats.t.cdf((beta-delta)/se,df))
    half=stats.t.ppf(.95,df)*se
    return {'p_tost':float(p),'ci90_low':float(beta-half),'ci90_high':float(beta+half),
            'equivalent':bool(p<.05),'margin':delta}

def describe(root):
    root=Path(root);out=root/'results';out.mkdir(exist_ok=True)
    x=pd.read_csv(root/'data/clean/nitrate_samples.csv',low_memory=False)
    q=pd.read_csv(root/'data/clean/nitrate_quarterly.csv');a=pd.read_csv(root/'data/clean/nitrate_annual.csv')
    g=pd.read_csv(root/'data/clean/coverage_grid.csv')
    # Eligibility is parsed explicitly, so text 'False' never becomes truthy.
    eligible=x.eligible.astype(str).str.lower().eq('true')
    x=x.loc[eligible].copy()
    stage=(x.groupby('stage').agg(n_samples=('SIX_YEAR_ID','size'),n_pws=('pwsid','nunique'),
                                 censored_share=('censored','mean')).reset_index())
    stage.to_csv(out/'observed_stage_coverage.csv',index=False)
    yearly=(x.groupby('year').agg(n_samples=('SIX_YEAR_ID','size'),n_pws=('pwsid','nunique'),
                                 n_staged=('stage',lambda s:s.ne('unresolved').sum())).reset_index())
    # Avoid mixing raw and finished stages. This is expressly an unknown-stage monitoring series.
    monitoring=a.loc[a.stage.eq('unresolved')]
    means=monitoring.groupby('year').agg(system_mean=('nitrate_mid','mean'),
                                       mean_lower=('nitrate_lower','mean'),mean_upper=('nitrate_upper','mean'),
                                       n_system_years=('pwsid','nunique')).reset_index()
    yearly=yearly.merge(means,on='year',how='left');yearly.to_csv(out/'observed_yearly_description.csv',index=False)
    coverage=g.groupby('year').agg(n_observed=('observed','sum'),n_possible=('pwsid','size'),
                                    median_quarters=('n_quarters','median')).reset_index()
    coverage.to_csv(out/'observed_sampling_coverage.csv',index=False)
    fig,axs=plt.subplots(1,2,figsize=(10.5,4))
    plt.rcParams['svg.fonttype']='none'
    ss=stage.sort_values('n_samples').copy()
    ss['label']=ss.stage.map({'raw':'Raw water','finished_or_entry':'Finished or entry','unresolved':'Unresolved stage'})
    axs[0].barh(ss.label,ss.n_samples,color='#365b78')
    for i,n in enumerate(ss.n_samples):axs[0].text(n+200,i,f'{n:,}',va='center',fontsize=9)
    axs[0].set_xlim(0,ss.n_samples.max()*1.23)
    axs[0].set_xlabel('Eligible community monitoring samples');axs[0].set_title('A  Water stage recorded in EPA data')
    axs[1].plot(coverage.year,coverage.n_observed,'o-',color='#365b78',label='Observed at least once')
    axs[1].plot(coverage.year,coverage.n_possible,'--',color='gray',label='Systems appearing in release')
    axs[1].set_xlabel('Year');axs[1].set_ylabel('Community systems');axs[1].set_title('B  Coverage varies by year');axs[1].legend(fontsize=8)
    for ax in axs:ax.spines[['top','right']].set_visible(False)
    fig.tight_layout();fig.savefig(out/'observed_data_coverage.svg');fig.savefig(out/'observed_data_coverage.png',dpi=250);plt.close(fig)
    # A missing crosswalk is a scientific stop condition, not evidence of no effect.
    readiness={'causal_analysis_status':'NOT ESTIMATED',
               'reason':'No independently validated time-varying facility to source or supply-network crosswalk',
               'available_observed_period':'2012-2019',
               'finished_stage_requires_review':'finished_or_entry includes entry and distribution points; labels do not verify source connectivity',
               'weather_controls':'No measured local weather file acquired; no synthetic weather inserted',
               'unsupported_claims':['zero causal effect','statewide equivalence','attribution of 2025-2026 spikes']}
    (out/'causal_analysis_status.json').write_text(json.dumps(readiness,indent=2))
    print(stage.to_string(index=False));print(yearly.to_string(index=False));print(json.dumps(readiness,indent=2))

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.')
    ap.add_argument('--design',help='Reviewed exposure CSV; omitted by default')
    ap.add_argument('--phase',choices=['construction','operation'],default='construction')
    ap.add_argument('--stage',choices=['raw','finished_or_entry'],default='finished_or_entry')
    ap.add_argument('--bootstrap',type=int,default=999);ap.add_argument('--anticipation',type=int,default=0)
    args=ap.parse_args();describe(args.root)
    if args.design:
        p=pd.read_csv(Path(args.root)/'data/clean/nitrate_quarterly.csv')
        d=validate_design(pd.read_csv(args.design,dtype=str),args.phase,'2019-12-31')
        p=p.loc[p.stage.eq(args.stage)]
        # Stage and linkage readiness must be resolved before entering this opt-in path.
        cells,events=bootstrap_dynamic(p,d,B=args.bootstrap,anticipation=args.anticipation)
        cells.to_csv(Path(args.root)/'results/reviewed_group_time_cells.csv',index=False)
        events.to_csv(Path(args.root)/'results/reviewed_dynamic_estimates.csv',index=False)

if __name__=='__main__':main()
