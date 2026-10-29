"""Explicit live compatibility check; credentials are read only from environment."""
import asyncio,json,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
from learning.provider import Gateway
from learning.schemas import Reply
from learning.db import now

async def main():
    g=Gateway();report={'timestamp':now(),'kind':'live_provider_probe','providers':[]}
    for p in g.providers:
        item={'provider':p.name,'base_url':p.base_url,'configured_model':p.model}
        async with httpx.AsyncClient(timeout=30,follow_redirects=False,trust_env=False) as c:
            try:
                r=await c.get(p.base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+p.key})
                item['models_status']=r.status_code
                if r.status_code==200:item['model_ids']=[x['id'] for x in r.json().get('data',[])]
            except Exception as e:item['models_error']=type(e).__name__
        report['providers'].append(item)
    try:
        out,meta=await g.call('chat',{'message':'接口测试，请回复：连接成功。citations为空，needs_human_review=true。'},Reply)
        report['generation']={'result':out.model_dump(),'metadata':meta}
    except Exception as exc:report['generation_error']=str(exc)
    target=Path(__file__).resolve().parents[1]/'evidence'/'deepseek-provider.json'
    target.parent.mkdir(exist_ok=True);target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))

if __name__=='__main__':asyncio.run(main())
