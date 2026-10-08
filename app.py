import csv, io, json, os, re, time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse, StreamingResponse
import httpx
from openpyxl import Workbook

app = FastAPI(title='MedResearch Agent V0.1')
HEADERS={'User-Agent':'MedResearchAgent/0.1 (research prototype)'}
CACHE={}

def clean_doi(s):
    return re.sub(r'^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)','',str(s or '').strip(),flags=re.I).lower()

def normalize_title(s):
    return re.sub(r'[^\w]+','',str(s or '').casefold())

def dedup(items):
    out=[]; seen=set()
    for item in items:
        doi=clean_doi(item.get('doi')); pmid=str(item.get('pmid') or '').strip(); nct=str(item.get('nct_id') or '').strip()
        keys=[('doi',doi)] if doi else []
        if pmid: keys.append(('pmid',pmid))
        if nct: keys.append(('nct',nct))
        title=normalize_title(item.get('title'))
        if title: keys.append(('title',title))
        if any(k in seen for k in keys): continue
        seen.update(keys);out.append(item)
    return out

async def get_json(url,params):
    async with httpx.AsyncClient(timeout=25,headers=HEADERS,follow_redirects=True) as client:
        for attempt in range(3):
            try:
                r=await client.get(url,params=params)
                if r.status_code in (429,500,502,503,504) and attempt<2:
                    await __import__('asyncio').sleep(1.5*(attempt+1));continue
                r.raise_for_status();return r.json()
            except (httpx.TimeoutException,httpx.ConnectError):
                if attempt==2:raise
                await __import__('asyncio').sleep(attempt+1)

async def pubmed(q,limit):
    base='https://eutils.ncbi.nlm.nih.gov/entrez/eutils/'
    params={'db':'pubmed','term':q,'retmode':'json','retmax':limit,'tool':'MedResearchAgent'}
    if os.getenv('NCBI_EMAIL'):params['email']=os.getenv('NCBI_EMAIL')
    if os.getenv('NCBI_API_KEY'):params['api_key']=os.getenv('NCBI_API_KEY')
    ids=(await get_json(base+'esearch.fcgi',params)).get('esearchresult',{}).get('idlist',[])
    if not ids:return []
    await __import__('asyncio').sleep(.36 if not os.getenv('NCBI_API_KEY') else .12)
    data=await get_json(base+'esummary.fcgi',{'db':'pubmed','id':','.join(ids),'retmode':'json',**({'api_key':os.getenv('NCBI_API_KEY')} if os.getenv('NCBI_API_KEY') else {})})
    result=data.get('result',{})
    items=[]
    for pmid in ids:
        r=result.get(pmid,{})
        doi=next((x.get('value','') for x in r.get('articleids',[]) if x.get('idtype')=='doi'),'')
        items.append({'source':'PubMed','title':r.get('title',''),'year':str(r.get('pubdate',''))[:4], 'authors':'; '.join(x.get('name','') for x in r.get('authors',[])), 'pmid':pmid,'doi':doi,'nct_id':'','url':f'https://pubmed.ncbi.nlm.nih.gov/{pmid}/'})
    return items

async def europe(q,limit):
    data=await get_json('https://www.ebi.ac.uk/europepmc/webservices/rest/search',{'query':q,'format':'json','pageSize':limit,'resultType':'core'})
    return [{'source':'Europe PMC','title':r.get('title',''),'year':str(r.get('pubYear','')),'authors':r.get('authorString',''),'pmid':r.get('pmid',''),'doi':r.get('doi',''),'nct_id':'','url':f'https://europepmc.org/article/{r.get("source","MED")}/{r.get("id","")}'} for r in data.get('resultList',{}).get('result',[])]

async def trials(q,limit):
    data=await get_json('https://clinicaltrials.gov/api/v2/studies',{'query.term':q,'pageSize':limit,'format':'json'})
    items=[]
    for r in data.get('studies',[]):
        p=r.get('protocolSection',{});i=p.get('identificationModule',{});n=i.get('nctId','')
        items.append({'source':'ClinicalTrials.gov','title':i.get('briefTitle',''),'year':str(p.get('statusModule',{}).get('studyFirstSubmitDate',''))[:4], 'authors':'','pmid':'','doi':'','nct_id':n,'url':f'https://clinicaltrials.gov/study/{n}'})
    return items

async def crossref(q,limit):
    data=await get_json('https://api.crossref.org/works',{'query.bibliographic':q,'rows':limit,'select':'DOI,title,author,published,URL'})
    items=[]
    for r in data.get('message',{}).get('items',[]):
        parts=r.get('published',{}).get('date-parts',[[None]])
        items.append({'source':'Crossref','title':(r.get('title') or [''])[0],'year':str(parts[0][0] or ''),'authors':'; '.join((a.get('given','')+' '+a.get('family','')).strip() for a in r.get('author',[])), 'pmid':'','doi':r.get('DOI',''),'nct_id':'','url':r.get('URL','')})
    return items

PROVIDERS={'pubmed':pubmed,'europepmc':europe,'clinicaltrials':trials,'crossref':crossref}
@app.get('/',response_class=HTMLResponse)
def home():
    return '''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MedResearch Agent</title><style>body{font-family:system-ui;max-width:900px;margin:35px auto;padding:18px;background:#f5f7fb;color:#162238}input,button{padding:12px;border-radius:8px;border:1px solid #b8c4d5}input{width:70%}button{background:#174ea6;color:white;cursor:pointer}table{border-collapse:collapse;width:100%;background:white}td,th{padding:10px;border-bottom:1px solid #ddd;text-align:left}small{color:#52627a}</style><h1>MedResearch Agent V0.1</h1><p>医学文献与临床试验检索 · DOI/PMID核验 · 去重 · 导出</p><input id="q" placeholder="例如 mild cognitive impairment tai chi"><button onclick="search()">检索</button><p><label><input type="checkbox" id="p" checked style="width:auto">PubMed</label> <label><input type="checkbox" id="e" checked style="width:auto">Europe PMC</label> <label><input type="checkbox" id="c" checked style="width:auto">Crossref</label> <label><input type="checkbox" id="t" checked style="width:auto">ClinicalTrials.gov</label></p><p id="status"></p><p><a id="csv" hidden>CSV导出</a>　<a id="xlsx" hidden>Excel导出</a>　<a id="ris" hidden>RIS导出</a></p><div style="overflow:auto"><table><thead><tr><th>标题</th><th>年份</th><th>来源</th><th>PMID</th><th>DOI</th></tr></thead><tbody id="rows"></tbody></table></div><script>async function search(){let q=document.getElementById('q').value.trim();if(!q)return;let sources=[['p','pubmed'],['e','europepmc'],['c','crossref'],['t','clinicaltrials']].filter(x=>document.getElementById(x[0]).checked).map(x=>x[1]);document.getElementById('status').textContent='正在检索...';try{let r=await fetch('/api/search?q='+encodeURIComponent(q)+'&sources='+sources.join(','));let j=await r.json();if(!r.ok)throw Error(JSON.stringify(j));document.getElementById('status').textContent='原始记录 '+j.raw_count+' 条；去重后 '+j.count+' 条。'+JSON.stringify(j.errors);let tbody=document.getElementById('rows');tbody.replaceChildren();for(let x of j.items){let tr=document.createElement('tr');for(let v of [x.title,x.year,x.source,x.pmid,x.doi]){let td=document.createElement('td');td.textContent=v||'';tr.appendChild(td)}tbody.appendChild(tr)}for(let f of ['csv','xlsx','ris']){let a=document.getElementById(f);a.hidden=false;a.href='/api/export/'+f+'?job='+j.job;a.textContent=f.toUpperCase()+' 导出'}}catch(e){document.getElementById('status').textContent='检索失败：'+e.message}}</script></html>'''

@app.get('/api/search')
async def search(q:str=Query(min_length=2),sources:str='pubmed,europepmc,crossref,clinicaltrials',limit:int=Query(20,ge=1,le=100)):
    chosen=[x.strip().lower() for x in sources.split(',') if x.strip()]
    if not chosen or any(x not in PROVIDERS for x in chosen):raise HTTPException(400,'Invalid sources')
    items=[];errors={}
    for source in chosen:
        try:items.extend(await PROVIDERS[source](q,limit))
        except Exception as e:errors[source]=type(e).__name__+': '+str(e)[:160]
    if not items:raise HTTPException(502,detail={'message':'No records returned','errors':errors})
    unique=dedup(items);job=__import__('uuid').uuid4().hex
    CACHE[job]={'items':unique,'created':time.time(),'query':q,'sources':chosen}
    for key in list(CACHE):
        if time.time()-CACHE[key]['created']>3600:del CACHE[key]
    return {'job':job,'query':q,'sources':chosen,'raw_count':len(items),'count':len(unique),'items':unique,'errors':errors,'retrieved_at':datetime.now(timezone.utc).isoformat()}

@app.get('/api/verify/doi')
async def verify_doi(doi:str):
    d=clean_doi(doi)
    if not d or '/' not in d:raise HTTPException(400,'Invalid DOI')
    try:
        r=await get_json('https://api.crossref.org/works/'+__import__('urllib.parse',fromlist=['quote']).quote(d,safe='/'),{})
        return {'verified':True,'doi':d,'title':(r.get('message',{}).get('title') or [''])[0],'provider':'Crossref'}
    except httpx.HTTPStatusError as e:
        if e.response.status_code==404:return {'verified':False,'doi':d,'status':'not_found_in_crossref'}
        raise HTTPException(502,'Crossref unavailable')
    except Exception:raise HTTPException(502,'Crossref unavailable')

@app.get('/api/verify/pmid')
async def verify_pmid(pmid:str):
    if not re.fullmatch(r'\d{1,10}',pmid):raise HTTPException(400,'Invalid PMID')
    try:
        data=await get_json('https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi',{'db':'pubmed','id':pmid,'retmode':'json'})
        r=data.get('result',{}).get(pmid,{})
        return {'verified':bool(r.get('uid')),'pmid':pmid,'title':r.get('title',''),'provider':'PubMed'}
    except Exception:raise HTTPException(502,'PubMed unavailable')

@app.get('/api/export/{fmt}')
def export(fmt:str,job:str):
    if job not in CACHE:raise HTTPException(404,'Job expired')
    items=CACHE[job]['items'];fields=['source','title','year','authors','pmid','doi','nct_id','url']
    if fmt=='csv':
        f=io.StringIO();w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows([{k:r.get(k,'') for k in fields} for r in items]);content=f.getvalue().encode('utf-8-sig');mime='text/csv'
    elif fmt=='xlsx':
        wb=Workbook();ws=wb.active;ws.title='Records';ws.append(fields)
        for r in items:ws.append([r.get(k,'') for k in fields])
        f=io.BytesIO();wb.save(f);content=f.getvalue();mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    elif fmt=='ris':
        lines=[]
        for r in items:
            lines+=['TY  - '+('CLIN' if r.get('nct_id') else 'JOUR'),'TI  - '+r.get('title',''),'PY  - '+r.get('year','')]
            for a in r.get('authors','').split('; '):
                if a:lines.append('AU  - '+a)
            for tag,key in [('DO','doi'),('AN','pmid'),('UR','url')]:
                if r.get(key):lines.append(tag+'  - '+str(r[key]))
            lines+=['ER  - ','']
        content='\n'.join(lines).encode('utf-8');mime='application/x-research-info-systems'
    else:raise HTTPException(400,'Unsupported format')
    return StreamingResponse(io.BytesIO(content),media_type=mime,headers={'Content-Disposition':f'attachment; filename="medresearch.{fmt}"'})
