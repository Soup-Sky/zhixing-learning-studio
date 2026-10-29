"""Local multi-account login. Passwords are PBKDF2 hashed; session tokens are stored hashed."""
from __future__ import annotations
import hashlib
import hmac
import json
import re
import secrets
import time
from datetime import datetime,timezone,timedelta
from .db import Store,uid,now

ITERATIONS=240_000
SESSION_DAYS=30
USERNAME=re.compile(r'^[\w.-]{2,32}$')
BUILTIN_SOURCE_IDS={'openstax-c1','openstax-c2','mit-1801'}

class AuthError(ValueError):
    pass

def hash_password(password:str,salt:bytes|None=None)->str:
    salt=salt or secrets.token_bytes(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),salt,ITERATIONS)
    return f'pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}'

def check_password(password:str,stored:str)->bool:
    try:
        _,rounds,salt,digest=stored.split('$')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode('utf-8'),bytes.fromhex(salt),int(rounds))
    except (ValueError,TypeError):return False
    return hmac.compare_digest(actual.hex(),digest)

def token_hash(token:str)->str:return hashlib.sha256(token.encode('ascii','ignore')).hexdigest()

def public_user(row)->dict:
    return {'id':row[0],'username':row[1],'display_name':row[2],'role':row[3],'disabled':bool(row[4]),'created_at':row[5]}

USER_FIELDS='id,username,display_name,role,disabled,created_at'
# A real hash keeps unknown-user logins as slow as wrong-password logins.
DUMMY_HASH=hash_password('timing-equalizer')

class Accounts:
    def __init__(self,store:Store):
        self.store=store;self.failures={}
        with store.connection() as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS users(id TEXT PRIMARY KEY,username TEXT UNIQUE COLLATE NOCASE,display_name TEXT,role TEXT,disabled INTEGER DEFAULT 0,created_at TEXT,password_hash TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT,expires_at TEXT,created_at TEXT);
            ''')

    def needs_setup(self)->bool:
        with self.store.connection() as c:return c.execute('SELECT count(*) FROM users').fetchone()[0]==0

    @staticmethod
    def validate(username:str,password:str|None,display_name:str|None=None):
        if not USERNAME.match(username or ''):raise AuthError('用户名需为2到32位字母、数字、汉字、点、下划线或短横线。')
        if password is not None and len(password)<8:raise AuthError('密码至少8位。')
        if password is not None and len(password)>128:raise AuthError('密码不能超过128位。')
        if display_name is not None and len(display_name)>40:raise AuthError('显示名称不能超过40个字符。')

    def create_user(self,username:str,password:str,display_name:str='',role:str='learner')->dict:
        username=(username or '').strip();display_name=(display_name or '').strip() or username
        self.validate(username,password,display_name)
        if role not in ('admin','learner'):raise AuthError('未知角色。')
        user=(uid(),username,display_name,role,0,now())
        with self.store.connection() as c:
            if c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():raise AuthError('用户名已存在。')
            c.execute(f'INSERT INTO users({USER_FIELDS},password_hash) VALUES(?,?,?,?,?,?,?)',user+(hash_password(password),))
        return public_user(user)

    def setup_admin(self,username,password,display_name='')->dict:
        # Check and insert under the store lock so two first-run tabs cannot both become admin.
        with self.store.lock:
            if not self.needs_setup():raise AuthError('系统已初始化，请登录。')
            user=self.create_user(username,password,display_name,'admin')
            self.claim_unowned(user['id'])
            return user

    def claim_unowned(self,user_id:str):
        """Assign learning records created before accounts existed to the first administrator."""
        with self.store.connection() as c:
            for kind,id,raw in c.execute("SELECT kind,id,data FROM documents WHERE kind IN ('courses','sources')").fetchall():
                data=json.loads(raw)
                if data.get('owner_id') or (kind=='sources' and id in BUILTIN_SOURCE_IDS):continue
                data['owner_id']=user_id
                # Keep updated_at so the 90-day retention clock is not reset by the migration.
                c.execute('UPDATE documents SET data=? WHERE kind=? AND id=?',(json.dumps(data,ensure_ascii=False),kind,id))
            for id,raw in c.execute('SELECT id,data FROM tasks').fetchall():
                data=json.loads(raw)
                if not data.get('owner_id'):
                    data['owner_id']=user_id;c.execute('UPDATE tasks SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),id))

    def login(self,username:str,password:str)->tuple[str,dict]:
        key=(username or '').strip().lower()
        locked=self.failures.get(key)
        if locked and locked[0]>=5 and time.monotonic()-locked[1]<60:raise AuthError('登录失败次数过多，请1分钟后再试。')
        with self.store.connection() as c:
            row=c.execute(f'SELECT {USER_FIELDS},password_hash FROM users WHERE username=?',(username.strip(),)).fetchone()
        valid=check_password(password,row[6] if row else DUMMY_HASH) and row is not None
        if not valid or row[4]:
            count=(locked[0] if locked and time.monotonic()-locked[1]<60 else 0)+1
            self.failures[key]=(count,time.monotonic())
            raise AuthError('账号已停用，请联系管理员。' if valid else '用户名或密码错误。')
        self.failures.pop(key,None)
        token=secrets.token_urlsafe(32)
        expires=(datetime.now(timezone.utc)+timedelta(days=SESSION_DAYS)).isoformat()
        with self.store.connection() as c:
            c.execute('DELETE FROM sessions WHERE expires_at<?',(now(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(token_hash(token),row[0],expires,now()))
        return token,public_user(row)

    def user_for_token(self,token:str|None)->dict|None:
        if not token:return None
        with self.store.connection() as c:
            row=c.execute(f'SELECT {",".join("u."+f for f in USER_FIELDS.split(","))} FROM sessions s JOIN users u ON u.id=s.user_id '
                          'WHERE s.token_hash=? AND s.expires_at>? AND u.disabled=0',(token_hash(token),now())).fetchone()
        return public_user(row) if row else None

    def logout(self,token:str|None):
        if token:
            with self.store.connection() as c:c.execute('DELETE FROM sessions WHERE token_hash=?',(token_hash(token),))

    def get(self,user_id:str)->dict:
        with self.store.connection() as c:row=c.execute(f'SELECT {USER_FIELDS} FROM users WHERE id=?',(user_id,)).fetchone()
        if not row:raise KeyError(user_id)
        return public_user(row)

    def list(self)->list[dict]:
        with self.store.connection() as c:return [public_user(r) for r in c.execute(f'SELECT {USER_FIELDS} FROM users ORDER BY created_at').fetchall()]

    def _admins(self,c,exclude:str)->int:
        return c.execute("SELECT count(*) FROM users WHERE role='admin' AND disabled=0 AND id!=?",(exclude,)).fetchone()[0]

    def update(self,user_id:str,*,display_name=None,role=None,disabled=None)->dict:
        user=self.get(user_id)
        if display_name is not None:
            display_name=display_name.strip() or user['username'];self.validate(user['username'],None,display_name)
        if role is not None and role not in ('admin','learner'):raise AuthError('未知角色。')
        with self.store.lock,self.store.connection() as c:
            demoting=(role is not None and role!='admin') or bool(disabled)
            if user['role']=='admin' and demoting and self._admins(c,user_id)==0:raise AuthError('至少需要保留一个可用的管理员账号。')
            if display_name is not None:c.execute('UPDATE users SET display_name=? WHERE id=?',(display_name,user_id))
            if role is not None:c.execute('UPDATE users SET role=? WHERE id=?',(role,user_id))
            if disabled is not None:
                c.execute('UPDATE users SET disabled=? WHERE id=?',(int(bool(disabled)),user_id))
                if disabled:c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
        return self.get(user_id)

    def change_password(self,user_id:str,current:str,new:str,keep_token:str|None=None):
        with self.store.connection() as c:row=c.execute('SELECT password_hash FROM users WHERE id=?',(user_id,)).fetchone()
        if not row or not check_password(current,row[0]):raise AuthError('当前密码不正确。')
        self.set_password(user_id,new,keep_token)

    def set_password(self,user_id:str,new:str,keep_token:str|None=None):
        self.validate(self.get(user_id)['username'],new)
        with self.store.connection() as c:
            c.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(new),user_id))
            # Other devices or tabs signed in with the old password are signed out.
            c.execute('DELETE FROM sessions WHERE user_id=? AND token_hash!=?',(user_id,token_hash(keep_token) if keep_token else ''))

    def delete(self,user_id:str):
        user=self.get(user_id)
        with self.store.lock:
            with self.store.connection() as c:
                if user['role']=='admin' and self._admins(c,user_id)==0:raise AuthError('至少需要保留一个可用的管理员账号。')
            for course in [c for c in self.store.list('courses') if c.get('owner_id')==user_id]:self.store.delete_course(course['id'])
            with self.store.connection() as c:
                for kind,id,raw in c.execute("SELECT kind,id,data FROM documents WHERE kind='sources'").fetchall():
                    if json.loads(raw).get('owner_id')==user_id:c.execute('DELETE FROM documents WHERE kind=? AND id=?',(kind,id))
                c.execute('DELETE FROM sessions WHERE user_id=?',(user_id,))
                c.execute('DELETE FROM users WHERE id=?',(user_id,))
