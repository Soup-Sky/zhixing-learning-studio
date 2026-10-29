"""Offline server for browser checks: temporary database, in-memory vault, stubbed DeepSeek.

Never touches the real learning database, Windows Credential Manager or the network.
Prints one JSON line {"port", "stub_key", "notebook_answer"} once the server is listening.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from desktop import create_server  # noqa: E402
from learning.api import create_app  # noqa: E402
from learning.db import Store, now  # noqa: E402
from learning.engine import Engine  # noqa: E402
from learning.knowledge import builtin_course  # noqa: E402
from learning.provider import Gateway  # noqa: E402

STUB_KEY = 'sk-offline-e2e-stub-not-a-real-key'


class MemoryVault:
    available = True

    def __init__(self):
        self.key = None

    def load(self):
        return self.key

    def save(self, key):
        self.key = key

    def delete(self):
        self.key = None


def stub(request: httpx.Request) -> httpx.Response:
    if request.headers.get('authorization') != 'Bearer ' + STUB_KEY:
        return httpx.Response(401, json={'error': 'invalid key'})
    if request.url.path.endswith('/models'):
        return httpx.Response(200, json={'data': [{'id': 'deepseek-chat'}]})
    body = json.loads(request.content)
    system, user = body['messages'][0]['content'], json.loads(body['messages'][1]['content'])
    if 'grading智能体' not in system:
        # Only grading is exercised in the browser check; anything else must fail loudly.
        return httpx.Response(400, json={'error': 'stub only grades'})
    # Appeal re-grades score 0.7 so the page can show the original and the new score.
    score = 0.7 if 'appeal' in user else 0.6
    grade = {'items': [{'question_id': q['id'], 'score': score, 'feedback': '答案要点基本正确，步骤说明可以更完整。',
                        'evidence': '按量规逐项核对', 'error_type': '步骤不完整', 'needs_human_review': False}
                       for q in user['questions']],
             'explanation': '按量规逐题核对，重点看极限定义与左右极限的说明。'}
    return httpx.Response(200, json={'choices': [{'message': {'content': json.dumps(grade, ensure_ascii=False)}}],
                                     'usage': {'prompt_tokens': 120, 'completion_tokens': 60, 'total_tokens': 180}})


def seed(store: Store) -> str:
    """A pre-account demo course, so the first administrator also exercises the migration."""
    builtin = builtin_course()
    for source in builtin['sources']:
        store.put('sources', source['id'], source)
    units = builtin['units']
    order = [u['id'] for u in units]
    mastery = {u: {'status': 'unknown', 'score': None, 'failures': 0, 'evidence': []} for u in order}
    mastery[order[0]] = {'status': 'mastered', 'score': 1.0, 'failures': 0, 'evidence': ['h1'], 'ai_confidence': 'accepted'}
    mastery[order[1]] = {'status': 'learning', 'score': 0.5, 'failures': 1, 'evidence': ['h2']}
    feedback = lambda score: {'score': score, 'decision': 'advance' if score >= 0.8 else 'remedial', 'items': [],
                              'explanation': '本次练习覆盖极限的定义与单侧极限。', 'needs_human_review': False,
                              'ai_review': {'verdict': 'accepted', 'advice': '第 2 题的步骤说明可以更完整。', 'issues': []}}
    stamp = datetime.now(timezone.utc)
    course = {'id': 'demo-calculus', 'title': '微积分：从函数到极限', 'topic': '微积分', 'status': 'active',
              'created_at': (stamp - timedelta(days=5)).isoformat(), 'builtin': True,
              'profile': {'goal': '掌握单变量微积分基础，能够完成极限与导数入门题。'},
              'source_ids': [s['id'] for s in builtin['sources']], 'units': units, 'question_bank': builtin['questions'],
              'mastery': mastery, 'current_unit_id': order[1], 'trace': [], 'messages': [], 'processed': {},
              'plan': {'unit_order': order[:6], 'weekly_hours': 3, 'goal': '掌握单变量微积分基础', 'reason': '按前测结果安排先修单元，先补函数与极限基础。',
                       'sessions': [{'unit_id': u, 'minutes': 30, 'focus': '概念与例题'} for u in order[:6]]},
              'history': [{'id': 'h1', 'assignment_id': 'a1', 'unit_id': order[0], 'feedback': feedback(1.0),
                           'answers': [], 'created_at': (stamp - timedelta(days=3)).isoformat()},
                          {'id': 'h2', 'assignment_id': 'a2', 'unit_id': order[1], 'feedback': feedback(0.5),
                           'answers': [], 'created_at': (stamp - timedelta(days=1)).isoformat()}]}
    # An unsubmitted open-question practice for the second unit, as a lesson step would leave it.
    open_question = next(q for q in builtin['questions'] if q['kind'] == 'open' and q['unit_id'] == order[1])
    open_question = asyncio.run(Engine(store, None).validate_questions([dict(open_question)], set(order)))[0]
    lesson = {'title': units[1]['title'], 'body': '本节从函数值逼近的角度理解极限：当 $x$ 从两侧趋近 $a$ 时，$f(x)$ 趋于同一个值，才称极限存在。', 'examples': [],
              'misconceptions': [], 'citations': [], 'needs_human_review': False,
              'ai_review': {'verdict': 'accepted', 'advice': '结合数轴说明左右极限。', 'issues': []}}
    assignment = {'id': 'a-demo', 'unit_id': order[1], 'questions': [open_question], 'created_at': now(), 'submitted': False}
    course.update(lesson=lesson, assignment=assignment,
                  workspaces={order[1]: {'lesson': lesson, 'assignment': assignment}})
    store.put('courses', course['id'], course)
    question = next(q for q in builtin['questions'] if q['kind'] == 'expression' and q['unit_id'] == order[1])
    # Same validation the engine applies when it publishes a question.
    question = asyncio.run(Engine(store, None).validate_questions([dict(question)], set(order)))[0]
    for i, (stage, due) in enumerate(((0, -1), (1, 2))):
        dates = [(stamp + timedelta(days=d)).isoformat() for d in (due, due + 2, due + 6)]
        store.put('notebook', f'note-{i}', {'id': f'note-{i}', 'course_id': course['id'], 'unit_id': order[1],
                                           'question': question['prompt'], 'private_question': question, 'answer': '0',
                                           'feedback': '上次作答未通过，重点复习左右极限。', 'due_dates': dates,
                                           'next_due': dates[stage], 'stage': stage, 'created_at': now()})
    return str(question['expected_answer'])


def main() -> None:
    workdir = Path(tempfile.mkdtemp(prefix='zhixing-e2e-'))
    store = Store(workdir / 'learning.sqlite')
    answer = seed(store)
    app = create_app(db_path=store.path, gateway=Gateway([], transport=httpx.MockTransport(stub)), vault=MemoryVault())
    server = create_server(app, 0)
    app.state.shutdown = lambda: setattr(server, 'should_exit', True)

    def announce():
        while not server.started and not server.should_exit:
            time.sleep(0.05)
        if server.started:
            port = server.servers[0].sockets[0].getsockname()[1]
            print(json.dumps({'port': port, 'stub_key': STUB_KEY, 'notebook_answer': answer}), flush=True)

    threading.Thread(target=announce, daemon=True).start()
    try:
        server.run()
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    main()
