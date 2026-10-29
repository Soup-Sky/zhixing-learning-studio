import json
import httpx
import pytest
from pydantic import BaseModel
from learning.provider import Gateway, ProviderConfig, ProviderFailure

class Output(BaseModel):
    reply: str

def test_runtime_uses_only_official_deepseek(monkeypatch):
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'deepseek-test-key')
    monkeypatch.setenv('DEEPSEEK_BASE_URL', 'https://example.test/v1')
    providers = Gateway.from_env()
    assert len(providers) == 1
    assert providers[0].name == 'DeepSeek'
    assert providers[0].base_url == 'https://api.deepseek.com'
    assert providers[0].model == 'deepseek-chat'
    monkeypatch.delenv('DEEPSEEK_API_KEY')
    assert Gateway.from_env() == []

@pytest.mark.asyncio
async def test_deepseek_requests_json_output_mode():
    bodies=[]
    async def handler(request):
        bodies.append(request.content.decode())
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"reply":"ok"}'}}]})
    gateway=Gateway([ProviderConfig('DeepSeek','https://api.deepseek.com','deepseek-chat','test-key')],
                    transport=httpx.MockTransport(handler))
    await gateway.call('chat',{},Output)
    assert len(bodies)==1
    assert json.loads(bodies[0])['response_format']=={'type':'json_object'}

@pytest.mark.asyncio
async def test_balance_exhausted_switches_provider_and_records_usage():
    async def handler(request):
        if request.url.host == 'first.test':
            return httpx.Response(402, json={'error': {'message': 'balance'}})
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"reply":"real response"}'}}], 'usage':{'prompt_tokens':5,'completion_tokens':3}})
    g=Gateway([ProviderConfig('first','https://first.test/v1','a','key1'),ProviderConfig('second','https://second.test/v1','b','key2')],transport=httpx.MockTransport(handler))
    out, meta=await g.call('teaching',{},Output)
    assert out.reply=='real response'
    assert meta['provider']=='second' and meta['usage']['prompt_tokens']==5
    assert 'key1' not in str(meta)

@pytest.mark.asyncio
async def test_auth_error_is_not_retried():
    calls=[]
    async def handler(request):
        calls.append(request)
        return httpx.Response(401,json={'error':{'message':'private raw error'}})
    g=Gateway([ProviderConfig('first','https://first.test/v1','a','secret')],transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure):await g.call('teaching',{},Output)
    assert len(calls)==1

@pytest.mark.asyncio
async def test_invalid_json_repaired_once_and_never_mocked():
    calls=[]
    async def handler(request):
        calls.append(request)
        return httpx.Response(200,json={'choices':[{'message':{'content':'not json'}}]})
    g=Gateway([ProviderConfig('first','https://first.test/v1','a','secret')],transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure):await g.call('teaching',{},Output)
    assert len(calls)==2

@pytest.mark.asyncio
async def test_plan_without_goal_is_accepted_and_schema_failures_log_field_paths(caplog):
    # Shape of the real DeepSeek planning reply seen on 2026-10-27: everything except goal.
    from learning.schemas import Plan
    from learning.provider import log
    # The app logger does not propagate once logs.setup has run, so capture it directly.
    log.addHandler(caplog.handler)
    plan={'unit_order':['U1'],'reason':'前测未掌握','weekly_hours':2.5,'sessions':[{'unit_id':'U1','minutes':30,'focus':'概念'}]}
    async def handler(request):
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(plan,ensure_ascii=False)}}]})
    g=Gateway([ProviderConfig('DeepSeek','https://api.deepseek.com','deepseek-chat','secret')],transport=httpx.MockTransport(handler))
    out,_=await g.call('planning',{},Plan)
    assert out.goal==''
    try:
        with pytest.raises(ProviderFailure,match='格式校验失败'):await g.call('chat',{},Output)
    finally:log.removeHandler(caplog.handler)
    assert 'chat schema check failed (attempt 2): reply:missing' in caplog.text

@pytest.mark.asyncio
async def test_missing_key_fails_explicitly():
    with pytest.raises(ProviderFailure):await Gateway([]).call('teaching',{},Output)

@pytest.mark.asyncio
async def test_auth_failure_does_not_switch_to_backup():
    hosts=[]
    async def handler(request):
        hosts.append(request.url.host)
        return httpx.Response(401 if request.url.host=='first.test' else 200,
            json={'choices':[{'message':{'content':'{"reply":"backup"}'}}]})
    g=Gateway([ProviderConfig('first','https://first.test/v1','a','key1'),
               ProviderConfig('second','https://second.test/v1','b','key2')],transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderFailure,match='认证'):await g.call('teaching',{},Output)
    assert hosts==['first.test']

@pytest.mark.asyncio
async def test_fallback_cost_uses_each_provider_price():
    first_calls=0
    async def handler(request):
        nonlocal first_calls
        if request.url.host=='first.test':
            first_calls+=1
            if first_calls==1:
                return httpx.Response(200,json={'choices':[{'message':{'content':'invalid JSON'}}],
                                                'usage':{'prompt_tokens':1000000,'completion_tokens':1000000}})
            return httpx.Response(402)
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"reply":"ok"}'}}],
                                        'usage':{'prompt_tokens':1000000,'completion_tokens':1000000}})
    g=Gateway([ProviderConfig('first','https://first.test/v1','a','key1',1,1),
               ProviderConfig('second','https://second.test/v1','b','key2',2,3)],transport=httpx.MockTransport(handler))
    _,meta=await g.call('teaching',{},Output)
    assert meta['estimated_cost_cny']==7
