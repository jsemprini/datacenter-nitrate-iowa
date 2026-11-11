from pypdf import PdfReader
import concurrent.futures,urllib.request,json,re,pathlib,html
ROOT=pathlib.Path(__file__).resolve().parents[1]
r=PdfReader(ROOT/'source_original/Iowa Data Centers Nitrate Manuscript.pdf');refs=[]
for i,p in enumerate(r.pages):
 for a in p.get('/Annots',[]):
  obj=a.get_object();act=obj.get('/A',{});u=act.get('/URI','')
  if u.startswith('http'):refs.append((u,i+1))
urls=sorted(set(x[0] for x in refs));pages={u:sorted(set(p for z,p in refs if z==u)) for u in urls}
def fetch(u):
 row={'url':u,'pdf_pages':pages[u]}
 try:
  req=urllib.request.Request(u,headers={'User-Agent':'Mozilla/5.0'})
  with urllib.request.urlopen(req,timeout=15) as x:
   row.update(status=x.status,final_url=x.url);s=x.read(400000).decode(errors='replace')
   m=re.search(r'<title[^>]*>(.*?)</title>',s,re.I|re.S);row['page_title']=html.unescape(m[1].strip()) if m else None
 except Exception as e:row['error']=str(e)
 return row
with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:out=list(ex.map(fetch,urls))
(ROOT/'results/original_reference_link_audit.json').write_text(json.dumps(out,indent=2))
print('URLs',len(out),'HTTP200',sum(x.get('status')==200 for x in out))
for x in out:
 if x.get('status')!=200:print(x['url'],x.get('error'))
