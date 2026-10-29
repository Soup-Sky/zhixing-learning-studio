import pytest
import httpx
from learning.api import create_app
from learning.provider import Gateway

@pytest.mark.asyncio
async def test_missing_provider_ui_status_and_cross_site_write_blocked(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8877') as c:
        assert (await c.get('/api/status')).json()['configured'] is False
        r=await c.post('/api/courses',json={'topic':'math','goal':'learn'},headers={'Origin':'https://evil.example'})
        assert r.status_code==403

@pytest.mark.asyncio
async def test_api_unknown_records_do_not_leak_traceback(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]))
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8877') as c:
        assert (await c.post('/api/auth/setup',json={'username':'admin','password':'offline-pass'})).status_code==200
        r=await c.get('/api/courses/missing')
        assert r.status_code==404 and 'traceback' not in r.text.lower()
