"""1.3.0: teacher review channel, appeals, task control, progress stats, backup, logs, fixes."""
import asyncio
import copy
import logging
import sqlite3
import httpx
import pytest
from learning.api import create_app
from learning.db import Store
from learning.engine import Engine
from learning.provider import Gateway, redact
from learning import progression
from tests.test_accounts import client, setup_admin
from tests.test_engine import course, Fake


def test_redact_keeps_ordinary_words_and_still_hides_keys():
    assert redact('risk-free task-1 desk-lamp') == 'risk-free task-1 desk-lamp'
    fake_key = 'sk-' + 'a' * 20
    assert redact('key ' + fake_key + ' end') == 'key [REDACTED] end'
    assert redact({'api_key': 'x', 'note': 'ok'}) == {'note': 'ok'}


def test_practice_before_pretest_keeps_diagnostic_stage():
    c = course(); c['status'] = 'diagnostic'; c.pop('plan')
    c['history'] = [{'id': 'h', 'unit_id': 'u1', 'feedback': {'score': 1.0, 'explanation': ''}}]
    progression.recompute(c)
    assert c['status'] == 'diagnostic' and c['mastery']['u1']['status'] == 'mastered'


def test_prerequisite_walk_visits_each_unit_once():
    # A wide diamond lattice made the old recursion exponential.
    units = [{'id': 'u0', 'prerequisites': []}]
    for i in range(1, 40):
        units.append({'id': f'u{i}', 'prerequisites': [f'u{j}' for j in range(max(0, i - 3), i)]})
    assert progression.with_prerequisites(units, {'u39'}) == {f'u{i}' for i in range(39)}


def test_review_due_dates_count_from_the_review():
    from datetime import datetime, timezone
    at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert progression.due_after(1, at).startswith('2026-01-04')
    assert progression.due_after(3, at) is None


class PlanFails:
    """Grades the pretest, then the planning call fails once."""
    def __init__(self): self.plans = 0
    async def call(self, role, payload, schema):
        if role == 'grading': return await Fake().call(role, payload, schema)
        if role == 'planning':
            self.plans += 1
            if self.plans == 1: raise ValueError('计划生成失败')
            return await Fake().call(role, payload, schema)
        raise AssertionError(role)


@pytest.mark.asyncio
async def test_failed_planning_keeps_graded_pretest_and_retry_only_replans(tmp_path, monkeypatch):
    db = Store(tmp_path / 'db'); c = course(); c['status'] = 'diagnostic'; c.pop('plan')
    c['diagnostic'] = {'questions': copy.deepcopy(c['assignment']['questions'])}
    db.put('courses', 'c', c); fake = PlanFails(); e = Engine(db, fake)
    answers = {'answers': [{'question_id': 'q', 'answer': '2'}]}
    with pytest.raises(ValueError): await e.diagnose('c', answers)
    saved = db.get('courses', 'c')
    assert saved['diagnostic_result']['score'] == 1 and saved['status'] == 'diagnostic'
    async def no_lesson(id, data, progress=None): return {'course_id': id}
    monkeypatch.setattr(e, 'lesson', no_lesson)
    grades = len([t for t in saved['trace'] if t['agent'] == 'grading'])
    await e.diagnose('c', answers)
    after = db.get('courses', 'c')
    assert after['status'] == 'active' and after['plan']['unit_order'] == ['u1', 'u2']
    assert len([t for t in after['trace'] if t['agent'] == 'grading']) == grades


@pytest.mark.asyncio
async def test_assessment_keeps_every_item_even_if_check_fails(tmp_path, monkeypatch):
    import learning.mathcheck as mc
    db = Store(tmp_path / 'db'); c = course()
    bank = [dict(c['assignment']['questions'][0], id=f'b{i}') for i in range(3)]
    c['question_bank'] = bank; db.put('courses', 'c', c); e = Engine(db, Fake())
    monkeypatch.setattr(mc, 'verify_problem', lambda q: {'status': 'incorrect'})
    result = await e.submit_assessment('c', {'kind': 'pre', 'answers': [{'question_id': 'b0', 'answer': '2'}], 'request_id': 'r'})
    assert len(result['items']) == 1 and result['course_id'] == 'c'


@pytest.mark.asyncio
async def test_submit_and_chat_results_name_course_and_unit(tmp_path):
    db = Store(tmp_path / 'db'); db.put('courses', 'c', course()); e = Engine(db, Fake())
    r = await e.submit('c', {'assignment_id': 'a', 'answers': [{'question_id': 'q', 'answer': '2'}], 'request_id': 'r'})
    assert (r['course_id'], r['unit_id'], r['action']) == ('c', 'u1', 'answers')
    assert (await e.submit('c', {'assignment_id': 'a', 'answers': [], 'request_id': 'r'}))['course_id'] == 'c'


@pytest.mark.asyncio
async def test_teacher_channel_lists_all_accounts_and_score_change_recomputes(tmp_path):
    app = create_app(tmp_path / 'db', Gateway([])); store = app.state.store
    async with client(app) as admin, client(app) as learner:
        await setup_admin(admin)
        student = (await admin.post('/api/users', json={'username': 'student', 'password': 'student-pass'})).json()
        c = course(); c['owner_id'] = student['id']; c['assignment']['questions'][0]['kind'] = 'open'
        store.put('courses', 'c', c)
        await Engine(store, Fake()).submit('c', {'assignment_id': 'a', 'answers': [{'question_id': 'q', 'answer': '解释'}], 'request_id': 'r'})
        await learner.post('/api/auth/login', json={'username': 'student', 'password': 'student-pass'})
        own = (await learner.get('/api/reviews')).json()
        assert own and all('content' not in r for r in own)
        assert (await learner.get('/api/teacher/reviews')).status_code == 403
        assert (await learner.post(f"/api/reviews/{own[0]['id']}/resolve", json={'action': 'approve', 'reason': 'x', 'request_id': 'r'})).status_code == 403
        queue = (await admin.get('/api/teacher/reviews')).json()
        grade = next(r for r in queue if r['kind'] == 'grade')
        assert grade['learner'] == 'student' and grade['teacher_status'] == 'open' and 'content' in grade
        r = await admin.post(f"/api/reviews/{grade['id']}/resolve", json={'action': 'revise', 'score': 0.4, 'reason': '论证不完整', 'request_id': 't1'})
        assert r.status_code == 200, r.text
        saved = store.get('courses', 'c')
        item = saved['history'][0]['feedback']['items'][0]
        assert item['score'] == 0.4 and item['original_score'] == 1 and item['teacher_review']['by'] == '管理员'
        assert saved['mastery']['u1']['status'] == 'learning'
        assert all(r['id'] != grade['id'] for r in (await admin.get('/api/teacher/reviews')).json())


@pytest.mark.asyncio
async def test_task_cancel_and_timeout(tmp_path, monkeypatch):
    import learning.api as api
    class Slow:
        providers = []
        async def call(self, role, payload, schema):
            await asyncio.sleep(30)
    app = create_app(tmp_path / 'db', Gateway([])); store = app.state.store
    app.state.engine.gateway = Slow()
    async with client(app) as c:
        owner = await setup_admin(c)
        x = course(); x['owner_id'] = owner['id']; store.put('courses', 'c', x)
        body = {'assignment_id': 'a', 'answers': [{'question_id': 'q', 'answer': '2'}], 'request_id': 'cancel-me'}
        task = (await c.post('/api/courses/c/answers', json=body)).json()['task_id']
        await asyncio.sleep(0.2)
        assert (await c.delete(f'/api/tasks/{task}')).json()['status'] == 'cancelled'
        await asyncio.sleep(0.2)
        t = (await c.get(f'/api/tasks/{task}')).json()
        assert t['status'] == 'cancelled' and t.get('finished_at')
    monkeypatch.setattr(api, 'TASK_TIMEOUT', 0.2)
    app = create_app(tmp_path / 'db2', Gateway([])); store = app.state.store
    app.state.engine.gateway = Slow()
    async with client(app) as c:
        owner = await setup_admin(c)
        x = course(); x['owner_id'] = owner['id']; store.put('courses', 'c', x)
        task = (await c.post('/api/courses/c/answers', json=body)).json()['task_id']
        for _ in range(30):
            await asyncio.sleep(0.1)
            t = (await c.get(f'/api/tasks/{task}')).json()
            if t['status'] != 'running': break
        assert t['status'] == 'failed' and '分钟' in t['error']


@pytest.mark.asyncio
async def test_admin_progress_backup_and_logs(tmp_path):
    from learning import logs
    app = create_app(tmp_path / 'db', Gateway([])); store = app.state.store
    path = logs.setup(tmp_path / 'logs')
    try:
        async with client(app) as admin, client(app) as learner:
            owner = await setup_admin(admin)
            await admin.post('/api/users', json={'username': 'student', 'password': 'student-pass'})
            c = course(); c['owner_id'] = owner['id']
            c['history'] = [{'id': 'h', 'unit_id': 'u1', 'answers': [{'answer': '私密作答'}], 'created_at': '2026-10-02',
                             'feedback': {'score': 1.0}}]
            c['messages'] = [{'role': 'user', 'content': '私密聊天'}]
            store.put('courses', 'c', c)
            progress = (await admin.get('/api/admin/progress')).json()
            assert {p['username'] for p in progress} == {'admin', 'student'}
            assert '私密' not in str(progress)
            mine = next(p for p in progress if p['username'] == 'admin')['courses'][0]
            assert mine['attempts'] == 1 and mine['average_score'] == 1.0
            backup = await admin.get('/api/admin/backup')
            assert backup.status_code == 200 and backup.content.startswith(b'SQLite format 3\x00')
            copy_path = tmp_path / 'copy.sqlite'; copy_path.write_bytes(backup.content)
            with sqlite3.connect(copy_path) as db:
                assert db.execute("SELECT count(*) FROM documents WHERE kind='courses'").fetchone()[0] == 1
            await learner.post('/api/auth/login', json={'username': 'student', 'password': 'student-pass'})
            for url in ('/api/admin/progress', '/api/admin/backup', '/api/admin/logs'):
                assert (await learner.get(url)).status_code == 403, url
            logs.log.error('provider said sk-%s', 'z' * 30)
            text = (await admin.get('/api/admin/logs')).text
            assert '[REDACTED]' in text and 'z' * 30 not in text
    finally:
        for handler in list(logs.log.handlers):
            handler.close(); logs.log.removeHandler(handler)
        for handler in list(logging.getLogger('uvicorn.error').handlers):
            if getattr(handler, 'baseFilename', '') == str(path.resolve()):
                logging.getLogger('uvicorn.error').removeHandler(handler)


@pytest.mark.asyncio
async def test_course_creation_lock_is_per_account_and_upload_limit_is_4mb(tmp_path):
    app = create_app(tmp_path / 'db', Gateway([]))
    async with client(app) as c:
        await setup_admin(c)
        big = b'x' * (4 * 1024 * 1024 + 10)
        r = await c.post('/api/sources/upload', files={'file': ('a.txt', big, 'text/plain')})
        assert r.status_code == 413 and '4 MB' in r.json()['detail']
        assert (await c.post('/api/settings/provider/test', json={'api_key': 'sk-has space inside'})).status_code == 400
