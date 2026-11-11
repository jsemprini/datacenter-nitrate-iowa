"""Download real public records with hashes; never generate substitute observations.

Run from the package root: python code/00_extract_public_data.py
The national EPA ZIP is cached, while the small Iowa extract is retained in data/.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import hashlib
import html
import json
from pathlib import Path
import re
import urllib.request
import zipfile
from datetime import datetime, timezone
import pandas as pd

EPA_ZIP = 'https://www.epa.gov/system/files/other-files/2024-03/_syr4_phasechem_4-hybrid-nitrate-to-nitrate.zip'
EPA_PAGE = 'https://www.epa.gov/dwsixyearreview/six-year-review-4-compliance-monitoring-data-2012-2019'
EPA_GUIDE = 'https://www.epa.gov/system/files/documents/2024-11/user-guide-to-downloading-and-using-syr4-data_0.pdf'
DNR_INDEX = 'https://programs.iowadnr.gov/sourcewater/'
MEMBER = 'SUMMARY_ANALYTE_NITRATE.txt'
EXPECTED_ZIP_SHA256 = '5b8726c9adee8fbfa0ca265393814439d0f5d1a552b7a88b0322d19ec9d738e0'

def sha256(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024*1024), b''): h.update(block)
    return h.hexdigest()

def download(url, path):
    """Atomic download; status records describe observed errors, never presumed CAPTCHAs."""
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={'User-Agent': 'IowaNitrateResearch/1.0'})
    record = {'url': url, 'retrieved_utc': datetime.now(timezone.utc).isoformat()}
    tmp = path.with_suffix(path.suffix+'.partial')
    try:
        with urllib.request.urlopen(request, timeout=60) as r, tmp.open('wb') as f:
            record.update(status=r.status, final_url=r.url)
            for block in iter(lambda: r.read(1024*1024), b''): f.write(block)
        tmp.replace(path)
        record.update(path=str(path), bytes=path.stat().st_size, sha256=sha256(path))
    except Exception as exc:
        tmp.unlink(missing_ok=True)
        record.update(error=type(exc).__name__+': '+str(exc))
    return record

def extract_iowa(archive, output):
    """Stream the EPA nitrate member, keeping all IA records and original fields.

    cp1252 is required by the released national file. Hybrid nitrate is not read:
    it includes nitrate/nitrite substitutions and would duplicate many records.
    """
    chunks = []
    with zipfile.ZipFile(archive) as z, z.open(MEMBER) as f:
        for chunk in pd.read_csv(f, sep='\t', encoding='cp1252', dtype=str, chunksize=100000):
            selected = chunk.loc[chunk.STATE_CODE.eq('IA')].copy()
            if len(selected): chunks.append(selected)
    if not chunks: raise ValueError('EPA release contains no Iowa nitrate records')
    data = pd.concat(chunks, ignore_index=True)
    if not data.ANALYTE_CODE.eq('1040').all(): raise ValueError('Unexpected analyte')
    data.to_csv(output, index=False)
    return {'rows': len(data), 'pws': data.PWSID.nunique(), 'output_sha256': sha256(output)}

def parse_dnr_index(text):
    rows=[]
    for tr in re.findall(r'<tr>(.*?)</tr>', text, flags=re.S|re.I):
        match=re.search(r"SystemDetail.aspx\?pwsid=(\d+)['\"]>(.*?)</a>", tr, re.I|re.S)
        if not match: continue
        cells=[html.unescape(re.sub('<[^>]+>', '', c)).replace('\xa0','').strip()
               for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S|re.I)]
        if len(cells)!=4: raise ValueError('DNR table schema changed')
        rows.append({'pwsid':'IA'+match[1].zfill(7), 'dnr_name':html.unescape(match[2]),
                     'population':cells[2], 'system_type':cells[3]})
    if not rows: raise ValueError('No systems parsed; inspect DNR page')
    return pd.DataFrame(rows)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',default='.')
    ap.add_argument('--wqp-year',type=int,help='Optional separate ambient-water coverage check')
    args=ap.parse_args();root=Path(args.root);raw=root/'data/raw';raw.mkdir(parents=True,exist_ok=True)
    cache=root/'cache';cache.mkdir(exist_ok=True);log=[]
    archive=cache/'syr4_nitrate.zip'
    if not archive.exists(): log.append(download(EPA_ZIP,archive))
    if not archive.exists():
        (raw/'acquisition_log.json').write_text(json.dumps(log,indent=2));raise SystemExit('EPA download failed; no observations were substituted')
    digest=sha256(archive)
    log.append({'source':EPA_ZIP,'sha256':digest,'matches_audited_release':digest==EXPECTED_ZIP_SHA256})
    # A changed release is retained but requires review before extracting into the audited dataset.
    if digest!=EXPECTED_ZIP_SHA256: raise SystemExit('EPA release checksum changed; inspect and explicitly update version')
    log.append(extract_iowa(archive,raw/'epa_syr4_iowa_nitrate_raw.csv'))
    for url,name in [(EPA_PAGE,'epa_syr4.html'),(EPA_GUIDE,'epa_syr4_guide.pdf'),(DNR_INDEX,'dnr_index.html')]:
        result=download(url,raw/name);log.append(result)
        if name=='dnr_index.html' and 'error' not in result:
            parse_dnr_index((raw/name).read_text()).to_csv(raw/'dnr_current_system_index.csv',index=False)
    if args.wqp_year:
        y=args.wqp_year
        url=('https://www.waterqualitydata.us/data/Result/search?statecode=US:19&'
             f'characteristicName=Nitrate&startDateLo=01-01-{y}&startDateHi=12-31-{y}&mimeType=csv&zip=no')
        log.append(download(url,raw/f'wqp_ambient_nitrate_{y}.csv'))
    (raw/'acquisition_log.json').write_text(json.dumps(log,indent=2))
    print(json.dumps(log,indent=2))

if __name__=='__main__': main()
