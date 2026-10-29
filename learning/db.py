from __future__ import annotations
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime,timezone,timedelta
from pathlib import Path
from .provider import redact

def now():return datetime.now(timezone.utc).isoformat()
def uid():return uuid.uuid4().hex

class Store:
    def __init__(self,path):
        self.path=Path(path)
        self.path.parent.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock()
        with self.connection() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents(kind TEXT,id TEXT,data TEXT,updated_at TEXT,PRIMARY KEY(kind,id));
            CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,request_key TEXT UNIQUE,data TEXT);
            ''')

    @contextmanager
    def connection(self):
        with self.lock:
            c=sqlite3.connect(self.path,timeout=20)
            try:
                with c:yield c
            finally:c.close()

    def put(self,kind,id,data):
        with self.connection() as c:self._put(c,kind,id,data)

    def _put(self,c,kind,id,data):
        c.execute('INSERT OR REPLACE INTO documents VALUES(?,?,?,?)',(kind,id,json.dumps(redact(data),ensure_ascii=False),now()))

    def save_bundle(self,course,documents=()):
        with self.connection() as c:
            self._put(c,'courses',course['id'],course)
            for kind,data in documents:self._put(c,kind,data['id'],data)

    def get(self,kind,id):
        with self.connection() as c:row=c.execute('SELECT data FROM documents WHERE kind=? AND id=?',(kind,id)).fetchone()
        if not row:raise KeyError(id)
        return json.loads(row[0])

    def list(self,kind):
        with self.connection() as c:rows=c.execute('SELECT data FROM documents WHERE kind=? ORDER BY updated_at DESC',(kind,)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def create_task(self,request_key,action,course_id,owner_id=None):
        with self.connection() as c:
            old=c.execute('SELECT data FROM tasks WHERE request_key=?',(request_key,)).fetchone()
            if old:return json.loads(old[0]),False
            task={'id':uid(),'action':action,'course_id':course_id,'owner_id':owner_id,'status':'queued','progress':[],'result':None,'created_at':now()}
            c.execute('INSERT INTO tasks VALUES(?,?,?)',(task['id'],request_key,json.dumps(task,ensure_ascii=False)))
            return task,True

    def task(self,id):
        with self.connection() as c:row=c.execute('SELECT data FROM tasks WHERE id=?',(id,)).fetchone()
        if not row:raise KeyError(id)
        return json.loads(row[0])

    def update_task(self,task):
        with self.connection() as c:c.execute('UPDATE tasks SET data=? WHERE id=?',(json.dumps(redact(task),ensure_ascii=False),task['id']))

    def recover_tasks(self):
        with self.connection() as c:
            for id,raw in c.execute('SELECT id,data FROM tasks').fetchall():
                data=json.loads(raw)
                if data['status'] in ('queued','running'):
                    data.update(status='failed',error='上次服务停止中断了任务。学习记录已保留，请重新操作。')
                    c.execute('UPDATE tasks SET data=? WHERE id=?',(json.dumps(data,ensure_ascii=False),id))

    def delete_course(self,id):
        with self.connection() as c:
            c.execute("DELETE FROM documents WHERE (kind='courses' AND id=?) OR json_extract(data,'$.course_id')=?",(id,id))
            c.execute("DELETE FROM tasks WHERE json_extract(data,'$.course_id')=?",(id,))

    def backup(self,target):
        """Consistent copy of the live WAL database, safe while the service keeps writing."""
        with self.lock:
            with sqlite3.connect(self.path,timeout=20) as source,sqlite3.connect(target) as destination:
                source.backup(destination)
            # Close explicitly: the context manager above only commits.
            source.close();destination.close()

    def touch(self,kind,id):
        """Refresh the retention clock without rewriting data a concurrent task may be saving."""
        with self.connection() as c:c.execute('UPDATE documents SET updated_at=? WHERE kind=? AND id=?',(now(),kind,id))

    def prune(self,days=90):
        cutoff=(datetime.now(timezone.utc)-timedelta(days=days)).isoformat()
        with self.connection() as c:
            expired=c.execute("SELECT id FROM documents WHERE kind='courses' AND updated_at<?",(cutoff,)).fetchall()
        for id, in expired:self.delete_course(id)
        with self.connection() as c:
            rows=c.execute('SELECT kind,id,data,updated_at FROM documents').fetchall()
            courses={id for kind,id,_,_ in rows if kind=='courses'}
            cited={sid for kind,_,raw,_ in rows if kind=='courses' for sid in json.loads(raw).get('source_ids',[])}
            for kind,id,raw,updated in rows:
                if kind=='courses':continue
                data=json.loads(raw)
                # Notebook items and reviews live exactly as long as their course, whatever their own age.
                orphan=bool(data.get('course_id')) and data['course_id'] not in courses
                # Built-in textbooks and the learner's own uploads stay until deleted by hand;
                # only stale automatic search results that no course cites are discarded.
                stale_search=kind=='sources' and 'search_snippet' in data and id not in cited and updated<cutoff
                if orphan or stale_search:c.execute('DELETE FROM documents WHERE kind=? AND id=?',(kind,id))
            for id,raw in c.execute('SELECT id,data FROM tasks').fetchall():
                if json.loads(raw).get('created_at','')<cutoff:c.execute('DELETE FROM tasks WHERE id=?',(id,))
