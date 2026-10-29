from __future__ import annotations
import asyncio
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime,timezone
from pathlib import Path
from fastapi import FastAPI,HTTPException,Request,UploadFile,File
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse,StreamingResponse,FileResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from .accounts import Accounts,AuthError,SESSION_DAYS
from .db import Store,uid,now
from .engine import Engine
from .provider import Gateway,KeyRejected,ProviderFailure,redact
from .schemas import CourseInput,Submission,LessonRequest,ChatRequest,ReviewRequest,Rubric
from .review_policy import public_review
from .sources import MAX_BYTES
from .version import VERSION
from .logs import log,current_file

ROOT=Path(__file__).resolve().parents[1]
# A task that runs longer than this is stopped; saved learning progress stays.
TASK_TIMEOUT=20*60
COOKIE='zhixing_session'
# /api/experiments only serves the bundled evidence files the public report page reads.
PUBLIC_API={'/api/status','/api/report','/api/experiments','/api/auth/state','/api/auth/login','/api/auth/setup','/api/auth/logout'}

class TextRequest(BaseModel):
    answers:str=Field(min_length=1,max_length=6000)
    request_id:str=Field(min_length=1,max_length=100)
class AppealRequest(BaseModel):
    reason:str=Field(min_length=1,max_length=4000)
    question_id:str|None=Field(default=None,max_length=100)
    history_id:str|None=Field(default=None,max_length=100)
    request_id:str=Field(min_length=1,max_length=100)
class URLRequest(BaseModel):
    url:str=Field(min_length=1,max_length=2000)
class NotebookRequest(BaseModel):
    answer:str=Field(min_length=1,max_length=8000)
    request_id:str=Field(min_length=1,max_length=100)
class AssessmentRequest(Submission):
    kind:str
class RubricRequest(BaseModel):
    assignment_id:str
    question_id:str
    rubric:list[Rubric]=Field(min_length=1)
    reason:str=Field(min_length=1,max_length=2000)
    request_id:str=Field(min_length=1,max_length=100)
class Credentials(BaseModel):
    username:str=Field(min_length=1,max_length=32)
    password:str=Field(min_length=1,max_length=128)
class NewUser(Credentials):
    display_name:str=Field(default='',max_length=40)
    role:str='learner'
class UserUpdate(BaseModel):
    display_name:str|None=Field(default=None,max_length=40)
    role:str|None=None
    disabled:bool|None=None
class ProfileUpdate(BaseModel):
    display_name:str=Field(max_length=40)
class PasswordChange(BaseModel):
    current:str=Field(min_length=1,max_length=128)
    new:str=Field(min_length=1,max_length=128)
class PasswordReset(BaseModel):
    password:str=Field(min_length=1,max_length=128)
class ProviderKey(BaseModel):
    api_key:str=Field(min_length=10,max_length=400)
    remember:bool=False
    verify:bool=True
class ProviderTest(BaseModel):
    api_key:str|None=Field(default=None,max_length=400)
class CourseUpdate(BaseModel):
    title:str=Field(min_length=1,max_length=80)

class NoVault:
    """Default for tests and the uvicorn dev entry: nothing is persisted."""
    available=False
    def load(self):return None
    def save(self,key):raise OSError('unsupported')
    def delete(self):pass

def course_progress(c,notebook):
    mastery={k:v for k,v in (c.get('mastery') or {}).items() if isinstance(v,dict)}
    order=(c.get('plan') or {}).get('unit_order') or [u['id'] for u in c.get('units') or []]
    statuses=[mastery.get(i,{}).get('status','unknown') for i in order]
    history=c.get('history') or []
    stamp=datetime.now(timezone.utc).isoformat()
    return {'planned_units':len(order),'mastered':statuses.count('mastered'),'learning':statuses.count('learning'),
            'attempts':len(history),
            'average_score':round(sum(h['feedback']['score'] for h in history)/len(history),3) if history else None,
            'last_activity':max([c.get('created_at') or '']+[h.get('created_at') or '' for h in history]),
            'notebook_total':len(notebook),
            'notebook_due':sum(1 for n in notebook if n.get('next_due') and n['next_due']<=stamp)}

def create_app(db_path=None,gateway=None,vault=None):
    store=Store(db_path or os.getenv('LEARNING_DB',str(ROOT/'data'/'learning.sqlite')))
    accounts=Accounts(store);vault=vault or NoVault()
    key_source={'value':None}
    if gateway is None:
        gateway=Gateway()
        if gateway.providers:key_source['value']='env'
        elif vault.available:
            try:stored=vault.load()
            except OSError:stored=None
            if stored:gateway.configure(stored);key_source['value']='vault'
    elif gateway.providers:key_source['value']='env'
    engine=Engine(store,gateway)
    running={};locks={}

    @asynccontextmanager
    async def lifespan(app):
        store.recover_tasks();store.prune(90)
        yield
        for task in list(running.values()):task.cancel()
        if running:await asyncio.gather(*running.values(),return_exceptions=True)

    app=FastAPI(title='知行 · 个性化学习工作室',version=VERSION,lifespan=lifespan)
    app.state.store=store;app.state.engine=engine;app.state.accounts=accounts
    # The desktop launcher installs a callback; dev servers are stopped from their console.
    app.state.shutdown=None
    @app.middleware('http')
    async def local_only(request,call_next):
        allowed={'127.0.0.1','localhost','testserver','::1'}
        if request.url.hostname not in allowed:return JSONResponse({'detail':'仅支持本机访问。'},403)
        if request.method not in ('GET','HEAD','OPTIONS'):
            # Writes must come from this exact origin. Other local ports share the
            # SameSite "site" on 127.0.0.1, so a port allowlist is not enough.
            origin=request.headers.get('origin')
            own=request.url.scheme+'://'+(request.headers.get('host') or '').lower()
            if origin and origin.lower().rstrip('/')!=own:return JSONResponse({'detail':'不允许跨站请求。'},403)
            if not origin and request.headers.get('sec-fetch-site') not in (None,'same-origin','none'):
                return JSONResponse({'detail':'不允许跨站请求。'},403)
        path=request.url.path
        request.state.token=request.cookies.get(COOKIE)
        request.state.user=accounts.user_for_token(request.state.token)
        if path.startswith('/api/') and path not in PUBLIC_API and request.state.user is None:
            return JSONResponse({'detail':'请先登录。','code':'login_required'},401)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff'
        response.headers['Referrer-Policy']='no-referrer'
        response.headers['Cache-Control']='no-store' if path.startswith('/api/') else 'no-cache'
        return response

    @app.exception_handler(KeyError)
    async def missing(request,exc):return JSONResponse({'detail':'记录不存在或已删除。'},404)
    @app.exception_handler(AuthError)
    async def auth_error(request,exc):return JSONResponse({'detail':str(exc)},400)
    @app.exception_handler(ValueError)
    async def invalid(request,exc):return JSONResponse({'detail':redact(str(exc))},422)
    @app.exception_handler(ProviderFailure)
    async def provider_error(request,exc):return JSONResponse({'detail':str(exc)},503)
    @app.exception_handler(Exception)
    async def unexpected(request,exc):
        log.error('%s %s failed: %s',request.method,request.url.path,type(exc).__name__,exc_info=exc)
        return JSONResponse({'detail':'服务内部错误（'+type(exc).__name__+'），已写入本机错误日志。'},500)
    @app.exception_handler(RequestValidationError)
    async def validation(request,exc):
        # FastAPI echoes rejected input by default; passwords and API keys must not come back.
        return JSONResponse({'detail':[{k:e.get(k) for k in ('loc','msg','type')} for e in exc.errors()]},422)

    def user(request)->dict:return request.state.user
    def admin(request)->dict:
        if request.state.user['role']!='admin':raise HTTPException(403,'仅管理员可以执行此操作。')
        return request.state.user
    def own_course(request,id):
        c=store.get('courses',id)
        # 404 rather than 403 so other accounts cannot probe which course IDs exist.
        if c.get('owner_id')!=user(request)['id']:raise KeyError(id)
        return c
    def visible_source(request,s):return s.get('owner_id') in (None,user(request)['id'])
    def own_notebook(request):
        ids={c['id'] for c in store.list('courses') if c.get('owner_id')==user(request)['id']}
        return [n for n in store.list('notebook') if n.get('course_id') in ids]

    def enqueue(request,action,course_id,request_id,work):
        owner=user(request)['id']
        task,new=store.create_task(f'{owner}:{course_id}:{action}:{request_id}',action,course_id,owner)
        if new:
            # Course creation has no course yet; one lock per account keeps accounts independent.
            lock=locks.setdefault(course_id if course_id!='new' else 'new:'+owner,asyncio.Lock())
            async def runner():
                try:
                    async with lock:
                        task.update(status='running',started_at=now());store.update_task(task)
                        def progress(message):task['progress'].append(message);store.update_task(task)
                        try:
                            result=await asyncio.wait_for(work(progress),TASK_TIMEOUT)
                            task.update(status='completed',result=redact(result))
                        except (ValueError,ProviderFailure) as exc:task.update(status='failed',error=redact(str(exc)))
                        except KeyError:task.update(status='failed',error='记录已删除或未找到，请刷新课程。')
                        except asyncio.TimeoutError:
                            log.warning('task %s (%s) timed out',task['id'],action)
                            task.update(status='failed',error=f'任务超过 {TASK_TIMEOUT//60} 分钟仍未完成，已停止。已保存的学习进度不受影响，请重试。')
                        except Exception as exc:
                            log.error('task %s (%s) failed: %s',task['id'],action,type(exc).__name__,exc_info=exc)
                            task.update(status='failed',error='任务未完成（'+type(exc).__name__+'）。已保存的学习进度不受影响，请重试。')
                except asyncio.CancelledError:
                    task.update(status='cancelled',error='任务已取消。已保存的学习进度不受影响。')
                    raise
                finally:
                    task['finished_at']=now();store.update_task(task)
            future=asyncio.create_task(runner());running[task['id']]=future
            future.add_done_callback(lambda _:running.pop(task['id'],None))
        return {'task_id':task['id']}

    def cancel_tasks(match):
        for id,future in list(running.items()):
            try:t=store.task(id)
            except KeyError:t={}
            if match(t):future.cancel()

    def own_task(request,id):
        t=store.task(id)
        if t.get('owner_id')!=user(request)['id']:raise KeyError(id)
        return t
    @app.get('/api/status')
    def status():return {'configured':bool(gateway.providers),'providers':gateway.status(),'version':VERSION,'retention_days':90,
                         'needs_setup':accounts.needs_setup()}

    def login_response(token,account):
        response=JSONResponse({'user':account})
        response.set_cookie(COOKIE,token,max_age=SESSION_DAYS*86400,httponly=True,samesite='strict',path='/')
        return response

    @app.get('/api/auth/state')
    def auth_state(request:Request):return {'needs_setup':accounts.needs_setup(),'user':request.state.user}

    @app.post('/api/auth/setup')
    def setup(data:NewUser):
        accounts.setup_admin(data.username,data.password,data.display_name)
        return login_response(*accounts.login(data.username,data.password))

    @app.post('/api/auth/login')
    def login(data:Credentials):return login_response(*accounts.login(data.username,data.password))

    @app.post('/api/auth/logout')
    def logout(request:Request):
        accounts.logout(request.state.token)
        response=JSONResponse({'ok':True});response.delete_cookie(COOKIE,path='/');return response

    @app.patch('/api/me')
    def update_me(request:Request,data:ProfileUpdate):return accounts.update(user(request)['id'],display_name=data.display_name)

    @app.post('/api/me/password')
    def change_password(request:Request,data:PasswordChange):
        accounts.change_password(user(request)['id'],data.current,data.new,request.state.token);return {'ok':True}

    @app.get('/api/users')
    def users(request:Request):
        admin(request)
        counts={}
        for c in store.list('courses'):counts[c.get('owner_id')]=counts.get(c.get('owner_id'),0)+1
        return [u|{'course_count':counts.get(u['id'],0)} for u in accounts.list()]

    @app.post('/api/users')
    def add_user(request:Request,data:NewUser):
        admin(request);return accounts.create_user(data.username,data.password,data.display_name,data.role)

    @app.patch('/api/users/{user_id}')
    def edit_user(request:Request,user_id:str,data:UserUpdate):
        if admin(request)['id']==user_id and (data.disabled or data.role=='learner'):raise AuthError('不能停用或降级当前登录的管理员账号。')
        return accounts.update(user_id,display_name=data.display_name,role=data.role,disabled=data.disabled)

    @app.post('/api/users/{user_id}/password')
    def reset_password(request:Request,user_id:str,data:PasswordReset):
        admin(request);accounts.set_password(user_id,data.password);return {'ok':True}

    @app.delete('/api/users/{user_id}')
    def delete_user(request:Request,user_id:str):
        if admin(request)['id']==user_id:raise AuthError('不能删除当前登录的账号。')
        accounts.delete(user_id)
        # A running task would otherwise write the deleted account's course back.
        cancel_tasks(lambda t:t.get('owner_id')==user_id)
        return {'ok':True}

    def provider_state():
        return {'configured':bool(gateway.providers),'source':key_source['value'],'remember_supported':vault.available,
                'model':gateway.providers[0].model if gateway.providers else Gateway.deepseek('').model,
                'exhausted':bool(gateway.exhausted)}

    @app.get('/api/settings/provider')
    def provider_settings(request:Request):admin(request);return provider_state()

    @app.put('/api/settings/provider')
    async def set_provider(request:Request,data:ProviderKey):
        admin(request);key=data.api_key.strip()
        if any(ch.isspace() for ch in key) or not key.isascii():raise AuthError('密钥格式不正确，请只粘贴密钥本身。')
        if data.verify:
            # A rejected key is never stored; only an unreachable DeepSeek may be bypassed by the admin.
            try:await gateway.check(key)
            except KeyRejected as exc:raise AuthError(str(exc)) from None
            except ProviderFailure as exc:
                return JSONResponse({'detail':str(exc)+' 可以选择暂不验证、直接保存。','code':'unverified'},503)
        try:
            if data.remember:
                if not vault.available:raise AuthError('此设备不支持记住密钥，请取消勾选后仅本次使用。')
                vault.save(key)
            else:vault.delete()
        except OSError:raise AuthError('Windows 凭据管理器拒绝了操作，请取消“记住密钥”后重试。') from None
        gateway.configure(key);key_source['value']='vault' if data.remember else 'session'
        return provider_state()|{'verified':data.verify}

    @app.post('/api/settings/provider/test')
    async def test_provider(request:Request,data:ProviderTest):
        admin(request)
        key=(data.api_key or '').strip() or (gateway.providers[0].key if gateway.providers else '')
        if not key:raise AuthError('尚未填写密钥。')
        if any(ch.isspace() for ch in key) or not key.isascii():raise AuthError('密钥格式不正确，请只粘贴密钥本身。')
        try:await gateway.check(key)
        except KeyRejected as exc:raise AuthError(str(exc)) from None
        return {'ok':True}

    @app.delete('/api/settings/provider')
    def clear_provider(request:Request):
        admin(request)
        try:vault.delete()
        except OSError:raise AuthError('Windows 凭据管理器拒绝清除密钥。') from None
        previous=key_source['value'];gateway.clear();key_source['value']=None
        return provider_state()|{'notice':'密钥来自 DEEPSEEK_API_KEY 环境变量，下次启动仍会读取，请同时删除该变量。' if previous=='env' else ''}

    @app.get('/api/system/info')
    def system_info(request:Request):
        info={'version':VERSION,'retention_days':90,'can_shutdown':app.state.shutdown is not None}
        if user(request)['role']!='admin':return info
        # Totals only, no content: the administrator pays for the shared key.
        usage={'calls':0,'prompt_tokens':0,'completion_tokens':0,'estimated_cost_cny':0.0}
        for c in store.list('courses'):
            for t in c.get('trace',[]):
                usage['calls']+=1
                for k in ('prompt_tokens','completion_tokens'):usage[k]+=int((t.get('usage') or {}).get(k,0) or 0)
                usage['estimated_cost_cny']+=float(t.get('estimated_cost_cny') or 0)
        usage['estimated_cost_cny']=round(usage['estimated_cost_cny'],4)
        log_file=current_file()
        return info|{'database':str(store.path),'usage':usage,'log_file':str(log_file) if log_file else None}

    @app.get('/api/admin/progress')
    def learner_progress(request:Request):
        """Per-account progress for the administrator: counts and scores only, never answers or chats."""
        admin(request)
        courses=store.list('courses');notebook=store.list('notebook');result=[]
        for u in accounts.list():
            mine=[c for c in courses if c.get('owner_id')==u['id']]
            rows=[]
            for c in mine:
                trace=c.get('trace',[])
                rows.append({'id':c['id'],'title':c.get('title'),'status':c.get('status'),
                    **course_progress(c,[n for n in notebook if n.get('course_id')==c['id']]),
                    'ai_calls':len(trace),
                    'tokens':sum(int((t.get('usage') or {}).get(k,0) or 0) for t in trace for k in ('prompt_tokens','completion_tokens'))})
            result.append({'user_id':u['id'],'username':u['username'],'display_name':u.get('display_name'),'role':u['role'],
                           'disabled':u.get('disabled',False),'courses':rows,
                           'last_activity':max([r['last_activity'] for r in rows] or [None],key=lambda x:x or '')})
        return result

    @app.get('/api/admin/backup')
    def backup(request:Request):
        """Download a consistent copy of the database. It contains password hashes and
        learner work, but never the DeepSeek key, which lives in Windows Credential Manager."""
        admin(request)
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'backup.sqlite'
            store.backup(target)
            body=target.read_bytes()
        stamp=datetime.now().strftime('%Y%m%d-%H%M%S')
        return Response(body,media_type='application/vnd.sqlite3',
                        headers={'Content-Disposition':f'attachment; filename="zhixing-backup-{stamp}.sqlite"'})

    @app.get('/api/admin/logs')
    def error_log(request:Request):
        admin(request)
        path=current_file()
        if path is None or not path.is_file():return Response('暂无错误日志。\n',media_type='text/plain; charset=utf-8')
        # The file is already redacted; return the newest part only.
        data=path.read_bytes()[-256*1024:]
        return Response(data.decode('utf-8','replace'),media_type='text/plain; charset=utf-8')

    @app.post('/api/system/shutdown')
    async def shutdown(request:Request):
        admin(request)
        if app.state.shutdown is None:raise HTTPException(409,'当前为开发模式，请在启动窗口按 Ctrl+C 结束服务。')
        # Let this response reach the browser before the server stops accepting connections.
        asyncio.get_running_loop().call_later(0.5,app.state.shutdown)
        return {'ok':True}
    @app.get('/api/courses')
    def courses(request:Request):
        fields=('id','title','topic','status','current_unit_id','created_at','profile','units','mastery')
        mine=[c for c in store.list('courses') if c.get('owner_id')==user(request)['id']]
        notebook=own_notebook(request)
        return [{k:c.get(k) for k in fields}|{'progress':course_progress(c,[n for n in notebook if n['course_id']==c['id']])} for c in mine]

    @app.post('/api/courses')
    async def create(request:Request,data:CourseInput):
        for id in data.source_ids:
            if not visible_source(request,store.get('sources',id)):raise KeyError(id)
        owner=user(request)['id']
        return enqueue(request,'create','new',data.request_id or uid(),lambda progress:engine.create(data.model_dump(),progress,owner))

    @app.get('/api/courses/{id}')
    def course(request:Request,id:str):
        own_course(request,id)
        # Opening a course counts as activity, so the 90-day clean-up never removes a course in use.
        store.touch('courses',id);return engine.view(id)

    @app.patch('/api/courses/{id}')
    async def rename(request:Request,id:str,data:CourseUpdate):
        async with locks.setdefault(id,asyncio.Lock()):
            c=own_course(request,id);c['title']=data.title.strip();store.put('courses',id,c)
        return {'ok':True,'title':c['title']}

    @app.get('/api/courses/{id}/units/{unit_id}')
    def workspace(request:Request,id:str,unit_id:str):own_course(request,id);return engine.workspace(id,unit_id)

    @app.get('/api/tasks/{id}')
    def task(request:Request,id:str):return own_task(request,id)

    @app.delete('/api/tasks/{id}')
    def cancel_task(request:Request,id:str):
        t=own_task(request,id)
        if t['status'] in ('completed','failed','cancelled'):return {'ok':True,'status':t['status']}
        future=running.get(id)
        if future:future.cancel()
        else:
            # No live worker (e.g. after a restart): close the record directly.
            t.update(status='cancelled',error='任务已取消。',finished_at=now());store.update_task(t)
        return {'ok':True,'status':'cancelled'}

    @app.get('/api/tasks/{id}/events')
    async def events(id:str,request:Request):
        own_task(request,id)
        async def stream():
            last=None
            while not await request.is_disconnected():
                current=store.task(id);encoded=json.dumps(current,ensure_ascii=False)
                if encoded!=last:yield 'data: '+encoded+'\n\n';last=encoded
                if current['status'] in ('completed','failed','cancelled'):break
                await asyncio.sleep(0.8)
        return StreamingResponse(stream(),media_type='text/event-stream')

    @app.post('/api/courses/{id}/clarify')
    async def clarify(request:Request,id:str,data:TextRequest):
        own_course(request,id)
        return enqueue(request,'clarify',id,data.request_id,lambda p:engine.clarify(id,data.answers,p))

    @app.post('/api/courses/{id}/diagnostic')
    async def diagnostic(request:Request,id:str,data:Submission):
        own_course(request,id)
        return enqueue(request,'diagnostic',id,data.request_id,lambda p:engine.diagnose(id,data.model_dump(),p))

    @app.post('/api/courses/{id}/lesson')
    async def lesson(request:Request,id:str,data:LessonRequest):
        own_course(request,id)
        return enqueue(request,'lesson',id,data.request_id,lambda p:engine.lesson(id,data.model_dump(),p))

    @app.post('/api/courses/{id}/answers')
    async def answers(request:Request,id:str,data:Submission):
        own_course(request,id)
        return enqueue(request,'answers',id,data.request_id,lambda p:engine.submit(id,data.model_dump(),p))

    @app.post('/api/courses/{id}/chat')
    async def chat(request:Request,id:str,data:ChatRequest):
        own_course(request,id)
        return enqueue(request,'chat',id,data.request_id,lambda p:engine.chat(id,data.model_dump(),p))

    @app.post('/api/courses/{id}/appeals')
    async def appeal(request:Request,id:str,data:AppealRequest):
        # An appeal re-grades one question with the model, so it runs as a task like grading.
        own_course(request,id)
        return enqueue(request,'appeal',id,data.request_id,lambda p:engine.appeal(id,data.model_dump(),p))

    @app.delete('/api/courses/{id}')
    async def delete(request:Request,id:str):
        own_course(request,id)
        # Stop queued work first; a waiting task would otherwise recreate the course.
        cancel_tasks(lambda t:t.get('course_id')==id)
        async with locks.setdefault(id,asyncio.Lock()):store.delete_course(id)
        return {'ok':True}

    @app.get('/api/courses/{id}/export')
    def export(request:Request,id:str):
        own_course(request,id)
        return JSONResponse(engine.view(id),headers={'Content-Disposition':f'attachment; filename="course-{id}.json"'})

    @app.get('/api/teacher/courses/{id}/trace')
    def teacher_trace(request:Request,id:str):
        # Raw traces contain answer keys, so learner accounts must not reach them before answering.
        admin(request)
        return {'notice':'本机教师视图包含参考答案，不应向正在作答的学生开放。','trace':own_course(request,id).get('trace',[])}
    @app.get('/api/sources')
    def sources(request:Request):
        used={}
        for c in store.list('courses'):
            if c.get('owner_id')!=user(request)['id']:continue
            for sid in c.get('source_ids',[]):used.setdefault(sid,[]).append({'id':c['id'],'title':c.get('title')})
        return [s|{'used_by':used.get(s['id'],[]),'shared':s.get('owner_id') is None}
                for s in store.list('sources') if visible_source(request,s)]

    @app.post('/api/sources/upload')
    async def upload(request:Request,file:UploadFile=File(...)):
        from .sources import extract_upload
        data=await file.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES:raise HTTPException(413,f'单个资料不得超过 {MAX_BYTES//1024//1024} MB。')
        source=await asyncio.to_thread(extract_upload,file.filename or '',data)
        source['owner_id']=user(request)['id'];store.put('sources',source['id'],source);return source

    @app.post('/api/sources/url')
    async def url(request:Request,data:URLRequest):
        from .sources import fetch_source
        source=await fetch_source(data.url)
        source['owner_id']=user(request)['id'];store.put('sources',source['id'],source);return source

    @app.delete('/api/sources/{id}')
    def delete_source(request:Request,id:str):
        s=store.get('sources',id)
        if not visible_source(request,s):raise KeyError(id)
        if s.get('owner_id') is None:raise AuthError('内置共享资料不能删除。')
        # Courses keep the citation ID; lessons simply skip a source that no longer exists.
        with store.connection() as c:c.execute("DELETE FROM documents WHERE kind='sources' AND id=?",(id,))
        return {'ok':True}

    @app.get('/api/reviews')
    def reviews(request:Request):
        # Stored content may hold answer keys, so learners only see the review status.
        ids={c['id'] for c in store.list('courses') if c.get('owner_id')==user(request)['id']}
        return [public_review(r) for r in store.list('reviews') if r.get('course_id') in ids]

    @app.get('/api/teacher/reviews')
    def teacher_reviews(request:Request,status:str='open'):
        """Teacher review channel across all accounts. AI review stays the default;
        these are the AI-uncertain records an administrator may confirm or correct."""
        admin(request)
        courses={c['id']:c for c in store.list('courses')}
        names={u['id']:u.get('display_name') or u['username'] for u in accounts.list()}
        result=[]
        for r in store.list('reviews'):
            if status!='all' and r.get('teacher_status','open' if r.get('ai_review',{}).get('verdict')=='uncertain' else 'none')!=status:continue
            c=courses.get(r.get('course_id'))
            if c is None:continue
            unit=next((u['title'] for u in c.get('units',[]) if u['id']==r.get('unit_id')),None)
            result.append(r|{'course_title':c.get('title'),'unit_title':unit,'learner':names.get(c.get('owner_id'),'未知账号')})
        return result

    @app.post('/api/reviews/{id}/resolve')
    async def resolve(request:Request,id:str,data:ReviewRequest):
        reviewer=admin(request);r=store.get('reviews',id)
        async with locks.setdefault(r['course_id'],asyncio.Lock()):
            return engine.resolve(id,data.model_dump(),reviewer.get('display_name') or reviewer['username'])

    @app.get('/api/notebook')
    def all_notebook(request:Request):
        return [{k:v for k,v in n.items() if k!='private_question'} for n in own_notebook(request)]

    @app.get('/api/courses/{id}/notebook')
    def notebook(request:Request,id:str):
        own_course(request,id)
        return [{k:v for k,v in n.items() if k!='private_question'} for n in store.list('notebook') if n['course_id']==id]

    @app.post('/api/courses/{id}/notebook/{item_id}/review')
    async def notebook_review(request:Request,id:str,item_id:str,data:NotebookRequest):
        own_course(request,id)
        return enqueue(request,'notebook',id,data.request_id,lambda p:engine.review_notebook(id,item_id,data.model_dump(),p))

    @app.get('/api/courses/{id}/assessment')
    def assessment(request:Request,id:str,kind:str='post'):own_course(request,id);return engine.assessment(id,kind)

    @app.post('/api/courses/{id}/assessment')
    async def assessment_submit(request:Request,id:str,data:AssessmentRequest):
        own_course(request,id)
        return enqueue(request,'assessment',id,data.request_id,lambda p:engine.submit_assessment(id,data.model_dump(),p))

    @app.post('/api/courses/{id}/rubric')
    async def rubric(request:Request,id:str,data:RubricRequest):
        # Rubric edits are a teacher action; a learner must not loosen their own grading.
        admin(request);own_course(request,id)
        async with locks.setdefault(id,asyncio.Lock()):
            c=store.get('courses',id);a=c.get('assignment') or {}
            if a.get('id')!=data.assignment_id:raise ValueError('作业已更新。')
            if a.get('submitted'):raise ValueError('已评分作业请通过复核修正，避免覆盖历史量规。')
            q=next((q for q in a['questions'] if q['id']==data.question_id),None)
            if q is None:raise ValueError('题目不存在。')
            if data.request_id in c.get('rubric_requests',[]):return {'ok':True}
            a.setdefault('rubric_history',[]).append({'question_id':q['id'],'previous':q['rubric'],'reason':data.reason})
            q['rubric']=[r.model_dump() for r in data.rubric];a['rubric_version']=a.get('rubric_version',1)+1
            c.setdefault('rubric_requests',[]).append(data.request_id);store.put('courses',id,c)
        return {'ok':True}

    @app.get('/api/experiments')
    def experiments():
        result=[]
        for file in (ROOT/'evidence').glob('*.json'):
            if file.name.startswith(('comparison','acceptance','live')):
                try:result.append({'file':file.name,'data':json.loads(file.read_text(encoding='utf-8'))})
                except (ValueError,OSError):pass
        return result

    @app.get('/api/report')
    def report():
        path=ROOT/'docs'/'项目汇报.html'
        if not path.exists():raise HTTPException(404,'报告尚未生成。')
        return FileResponse(path)

    dist=ROOT/'frontend'/'dist'
    if (dist/'assets').exists():app.mount('/assets',StaticFiles(directory=dist/'assets'),name='assets')
    @app.get('/{path:path}')
    def spa(path:str):
        if path.startswith('api/'):raise HTTPException(404,'接口不存在。')
        if not (dist/'index.html').exists():return JSONResponse({'detail':'前端尚未构建，请运行启动器完成安装。'},503)
        return FileResponse(dist/'index.html')
    return app
