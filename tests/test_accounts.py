import httpx
import pytest
from learning.api import create_app
from learning.db import Store
from learning.provider import Gateway

BASE='http://127.0.0.1:8877'
SECRET='sk-offline-test-not-real-0123456789'

class FakeVault:
    available=True
    def __init__(self,key=None):self.key=key
    def load(self):return self.key
    def save(self,key):self.key=key
    def delete(self):self.key=None

def deepseek_stub(request):
    ok=request.headers.get('authorization')=='Bearer '+SECRET
    return httpx.Response(200 if ok else 401,json={'data':[]})

def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=BASE)

async def setup_admin(c,username='admin',password='admin-pass-1'):
    r=await c.post('/api/auth/setup',json={'username':username,'password':password,'display_name':'管理员'})
    assert r.status_code==200,r.text
    return r.json()['user']

@pytest.mark.asyncio
async def test_first_run_setup_login_and_logout(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]))
    async with client(app) as c:
        assert (await c.get('/api/auth/state')).json()=={'needs_setup':True,'user':None}
        assert (await c.get('/api/courses')).status_code==401
        user=await setup_admin(c)
        assert user['role']=='admin' and 'password_hash' not in user
        assert (await c.get('/api/courses')).status_code==200
        # Setup is one-time; later accounts are created by an administrator.
        assert (await c.post('/api/auth/setup',json={'username':'second','password':'second-pass'})).status_code==400
        await c.post('/api/auth/logout')
        assert (await c.get('/api/courses')).status_code==401
        assert (await c.post('/api/auth/login',json={'username':'admin','password':'wrong-pass'})).status_code==400
        assert (await c.post('/api/auth/login',json={'username':'ADMIN','password':'admin-pass-1'})).status_code==200
        assert (await c.get('/api/auth/state')).json()['user']['username']=='admin'

@pytest.mark.asyncio
async def test_repeated_login_failures_are_throttled(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]))
    async with client(app) as c:
        await setup_admin(c)
        for _ in range(5):await c.post('/api/auth/login',json={'username':'admin','password':'wrong-pass'})
        r=await c.post('/api/auth/login',json={'username':'admin','password':'admin-pass-1'})
        assert r.status_code==400 and '过多' in r.json()['detail']

@pytest.mark.asyncio
async def test_accounts_cannot_see_each_others_learning_records(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]));store=app.state.store
    async with client(app) as admin,client(app) as learner:
        owner=await setup_admin(admin)
        r=await admin.post('/api/users',json={'username':'student','password':'student-pass','role':'learner'})
        assert r.status_code==200
        store.put('courses','c1',{'id':'c1','owner_id':owner['id'],'title':'私人课程','topic':'t','status':'active','units':[],'mastery':{},'history':[]})
        store.put('notebook','n1',{'id':'n1','course_id':'c1','unit_id':'u','question':'q','answer':'a','feedback':'f'})
        store.put('sources','private',{'id':'private','owner_id':owner['id'],'title':'私人资料','text':'x'})
        store.put('sources','shared',{'id':'shared','title':'内置资料','text':'x'})
        task,_=store.create_task('k','lesson','c1',owner['id'])
        assert (await learner.post('/api/auth/login',json={'username':'student','password':'student-pass'})).status_code==200
        assert [c['id'] for c in (await admin.get('/api/courses')).json()]==['c1']
        assert (await learner.get('/api/courses')).json()==[]
        for path in ('/api/courses/c1','/api/courses/c1/notebook','/api/courses/c1/export',f'/api/tasks/{task["id"]}'):
            assert (await learner.get(path)).status_code==404,path
        assert (await learner.delete('/api/courses/c1')).status_code==404
        assert (await learner.get('/api/notebook')).json()==[]
        assert {s['id'] for s in (await learner.get('/api/sources')).json()}=={'shared'}
        assert (await learner.delete('/api/sources/private')).status_code==404
        # Shared built-in material stays available to everyone and cannot be removed.
        assert (await admin.delete('/api/sources/shared')).status_code==400
        r=await learner.post('/api/courses',json={'topic':'math','background':'b','goal':'g','source_ids':['private']})
        assert r.status_code==404
        assert store.get('courses','c1')['title']=='私人课程'

@pytest.mark.asyncio
async def test_progress_summary_and_source_usage(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]));store=app.state.store
    async with client(app) as c:
        owner=await setup_admin(c)
        store.put('sources','s1',{'id':'s1','owner_id':owner['id'],'title':'讲义','text':'x'})
        store.put('courses','c1',{'id':'c1','owner_id':owner['id'],'title':'微积分','topic':'t','status':'active','created_at':'2026-10-01T00:00:00+00:00',
            'source_ids':['s1'],'units':[{'id':'a'},{'id':'b'},{'id':'c'}],'plan':{'unit_order':['a','b']},
            'mastery':{'a':{'status':'mastered'},'b':{'status':'learning'},'c':{'status':'unknown'}},
            'history':[{'feedback':{'score':1.0},'created_at':'2026-10-02T00:00:00+00:00'},{'feedback':{'score':0.5},'created_at':'2026-10-03T00:00:00+00:00'}]})
        store.put('notebook','n1',{'id':'n1','course_id':'c1','next_due':'2000-01-01T00:00:00+00:00'})
        progress=(await c.get('/api/courses')).json()[0]['progress']
        assert progress=={'planned_units':2,'mastered':1,'learning':1,'attempts':2,'average_score':0.75,
                          'last_activity':'2026-10-03T00:00:00+00:00','notebook_total':1,'notebook_due':1}
        assert (await c.get('/api/sources')).json()[0]['used_by']==[{'id':'c1','title':'微积分'}]
        assert (await c.patch('/api/courses/c1',json={'title':'微积分（重修）'})).json()['title']=='微积分（重修）'
        assert (await c.delete('/api/sources/s1')).status_code==200
        # Deleting material keeps the course and its citation IDs intact.
        assert (await c.get('/api/courses/c1')).status_code==200

@pytest.mark.asyncio
async def test_api_key_is_managed_in_web_settings_without_leaking(tmp_path):
    vault=FakeVault()
    app=create_app(tmp_path/'db',Gateway([],transport=httpx.MockTransport(deepseek_stub)),vault=vault)
    async with client(app) as admin,client(app) as learner:
        await setup_admin(admin)
        await admin.post('/api/users',json={'username':'student','password':'student-pass'})
        await learner.post('/api/auth/login',json={'username':'student','password':'student-pass'})
        assert (await learner.get('/api/settings/provider')).status_code==403
        assert (await learner.put('/api/settings/provider',json={'api_key':SECRET})).status_code==403
        assert (await admin.get('/api/status')).json()['configured'] is False
        r=await admin.put('/api/settings/provider',json={'api_key':SECRET,'remember':True})
        assert r.status_code==200 and r.json()['source']=='vault' and vault.key==SECRET
        # Takes effect immediately for every account without restarting.
        assert (await learner.get('/api/status')).json()['configured'] is True
        assert (await admin.post('/api/settings/provider/test',json={})).json()=={'ok':True}
        bad=await admin.post('/api/settings/provider/test',json={'api_key':'sk-wrong-key-000000'})
        assert bad.status_code==400 and 'sk-' not in bad.text
        # A key DeepSeek rejects is never stored, so the page cannot claim "configured".
        rejected_key=await admin.put('/api/settings/provider',json={'api_key':'sk-wrong-key-000000','remember':True})
        assert rejected_key.status_code==400 and vault.key==SECRET
        assert app.state.engine.gateway.providers[0].key==SECRET
        for response in (r,await admin.get('/api/settings/provider'),await admin.get('/api/status')):
            assert SECRET not in response.text
        # Validation errors must not echo the submitted secret back.
        rejected=await admin.put('/api/settings/provider',json={'api_key':SECRET,'remember':'not-a-bool'})
        assert rejected.status_code==422 and SECRET not in rejected.text
        session=await admin.put('/api/settings/provider',json={'api_key':SECRET,'remember':False})
        assert session.json()['source']=='session' and vault.key is None
        cleared=await admin.delete('/api/settings/provider')
        assert cleared.json()['configured'] is False and vault.key is None
        with sqlite_text(tmp_path/'db') as text:assert SECRET not in text

class sqlite_text:
    def __init__(self,path):self.path=path
    def __enter__(self):
        data=b''.join(p.read_bytes() for p in self.path.parent.glob(self.path.name+'*'))
        return data.decode('latin-1')
    def __exit__(self,*args):pass

@pytest.mark.asyncio
async def test_unreachable_deepseek_needs_explicit_unverified_save(tmp_path):
    def offline(request):raise httpx.ConnectError('offline',request=request)
    app=create_app(tmp_path/'db',Gateway([],transport=httpx.MockTransport(offline)),vault=FakeVault())
    async with client(app) as admin:
        await setup_admin(admin)
        r=await admin.put('/api/settings/provider',json={'api_key':SECRET})
        assert r.status_code==503 and r.json()['code']=='unverified'
        assert (await admin.get('/api/status')).json()['configured'] is False
        r=await admin.put('/api/settings/provider',json={'api_key':SECRET,'verify':False})
        assert r.status_code==200 and r.json()['verified'] is False and r.json()['configured'] is True

@pytest.mark.asyncio
async def test_writes_only_accepted_from_the_same_origin(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]))
    async with client(app) as c:
        await setup_admin(c)
        # Other ports on 127.0.0.1 share the cookie's SameSite "site", so they must be refused.
        for origin in ('http://127.0.0.1:5173','http://localhost:8877','http://127.0.0.1','https://evil.example'):
            r=await c.post('/api/system/shutdown',headers={'Origin':origin})
            assert r.status_code==403,origin
        r=await c.post('/api/system/shutdown',headers={'Sec-Fetch-Site':'same-site'})
        assert r.status_code==403
        # Same-origin browser writes and header-less local tools still work.
        assert (await c.post('/api/system/shutdown',headers={'Origin':BASE})).status_code==409
        assert (await c.post('/api/system/shutdown',headers={'Sec-Fetch-Site':'same-origin'})).status_code==409

@pytest.mark.asyncio
async def test_answer_keys_and_rubrics_are_teacher_only(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]));store=app.state.store
    async with client(app) as admin,client(app) as learner:
        owner=await setup_admin(admin)
        student=(await admin.post('/api/users',json={'username':'student','password':'student-pass'})).json()
        await learner.post('/api/auth/login',json={'username':'student','password':'student-pass'})
        for cid,uid_ in (('mine',student['id']),('teacher',owner['id'])):
            store.put('courses',cid,{'id':cid,'owner_id':uid_,'title':'t','trace':[{'agent':'assignment','output':{'expected_answer':'42'}}],
                                     'assignment':{'id':'a1','submitted':False,'questions':[{'id':'q1','rubric':[{'criterion':'c','points':1}]}]}})
        rubric={'assignment_id':'a1','question_id':'q1','rubric':[{'criterion':'全给分','points':1}],'reason':'r','request_id':'x1'}
        assert (await learner.get('/api/teacher/courses/mine/trace')).status_code==403
        assert (await learner.post('/api/courses/mine/rubric',json=rubric)).status_code==403
        assert store.get('courses','mine')['assignment']['questions'][0]['rubric'][0]['criterion']=='c'
        assert '42' in (await admin.get('/api/teacher/courses/teacher/trace')).text
        assert (await admin.post('/api/courses/teacher/rubric',json=rubric)).json()=={'ok':True}

@pytest.mark.asyncio
async def test_system_info_usage_is_admin_only_and_report_data_is_public(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]));store=app.state.store
    async with client(app) as admin,client(app) as learner,client(app) as anonymous:
        owner=await setup_admin(admin)
        await admin.post('/api/users',json={'username':'student','password':'student-pass'})
        await learner.post('/api/auth/login',json={'username':'student','password':'student-pass'})
        store.put('courses','c',{'id':'c','owner_id':owner['id'],'title':'t','trace':[
            {'usage':{'prompt_tokens':100,'completion_tokens':50},'estimated_cost_cny':0.0005},
            {'usage':{'prompt_tokens':10,'completion_tokens':5},'estimated_cost_cny':0.0002}]})
        info=(await admin.get('/api/system/info')).json()
        assert info['usage']=={'calls':2,'prompt_tokens':110,'completion_tokens':55,'estimated_cost_cny':0.0007}
        assert info['database'].endswith('db') and info['can_shutdown'] is False
        assert set((await learner.get('/api/system/info')).json())=={'version','retention_days','can_shutdown'}
        assert (await anonymous.get('/api/experiments')).status_code==200

@pytest.mark.asyncio
async def test_opening_a_course_keeps_it_from_retention_cleanup(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]));store=app.state.store
    async with client(app) as c:
        owner=await setup_admin(c)
        store.put('courses','c',{'id':'c','owner_id':owner['id'],'title':'t','units':[],'mastery':{}})
        with store.connection() as db:db.execute("UPDATE documents SET updated_at='2000-01-01T00:00:00+00:00'")
        assert (await c.get('/api/courses/c')).status_code==200
        store.prune(90)
        assert store.get('courses','c')['title']=='t'

def test_remembered_key_loads_at_startup(tmp_path):
    app=create_app(tmp_path/'db',vault=FakeVault(SECRET))
    assert app.state.engine.gateway.providers[0].key==SECRET

@pytest.mark.asyncio
async def test_admin_safeguards_and_session_revocation(tmp_path):
    app=create_app(tmp_path/'db',Gateway([]))
    async with client(app) as admin,client(app) as learner,client(app) as other_tab:
        me=await setup_admin(admin)
        assert (await admin.patch(f'/api/users/{me["id"]}',json={'role':'learner'})).status_code==400
        assert (await admin.delete(f'/api/users/{me["id"]}')).status_code==400
        student=(await admin.post('/api/users',json={'username':'student','password':'student-pass'})).json()
        assert (await admin.post('/api/users',json={'username':'Student','password':'another-pass'})).status_code==400
        await learner.post('/api/auth/login',json={'username':'student','password':'student-pass'})
        await other_tab.post('/api/auth/login',json={'username':'student','password':'student-pass'})
        assert (await learner.get('/api/users')).status_code==403
        assert (await learner.post('/api/system/shutdown')).status_code==403
        r=await learner.post('/api/me/password',json={'current':'student-pass','new':'student-pass-2'})
        assert r.status_code==200
        assert (await learner.get('/api/courses')).status_code==200
        assert (await other_tab.get('/api/courses')).status_code==401
        assert (await admin.patch(f'/api/users/{student["id"]}',json={'disabled':True})).json()['disabled'] is True
        assert (await learner.get('/api/courses')).status_code==401
        r=await learner.post('/api/auth/login',json={'username':'student','password':'student-pass-2'})
        assert r.status_code==400 and '停用' in r.json()['detail']
        app.state.store.put('courses','sc',{'id':'sc','owner_id':student['id'],'title':'t'})
        assert [u['course_count'] for u in (await admin.get('/api/users')).json()]==[0,1]
        assert (await admin.delete(f'/api/users/{student["id"]}')).status_code==200
        with pytest.raises(KeyError):app.state.store.get('courses','sc')
        # Without the desktop launcher there is no process to stop from the browser.
        assert (await admin.post('/api/system/shutdown')).status_code==409

@pytest.mark.asyncio
async def test_existing_records_are_claimed_by_first_administrator(tmp_path):
    legacy=Store(tmp_path/'db')
    legacy.put('courses','old',{'id':'old','title':'旧课程','topic':'t','status':'active','units':[],'mastery':{}})
    legacy.put('sources','upload',{'id':'upload','title':'上传资料','text':'x'})
    legacy.put('sources','openstax-c1',{'id':'openstax-c1','title':'OpenStax','text':'x'})
    app=create_app(tmp_path/'db',Gateway([]))
    async with client(app) as c:
        owner=await setup_admin(c)
        assert [x['id'] for x in (await c.get('/api/courses')).json()]==['old']
        sources={s['id']:s for s in (await c.get('/api/sources')).json()}
        assert sources['upload']['owner_id']==owner['id'] and sources['openstax-c1']['shared'] is True
