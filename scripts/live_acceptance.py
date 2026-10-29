"""Run synthetic learner scenarios against the local, real-model application."""
from __future__ import annotations

import json
import os
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx

BASE = 'http://127.0.0.1:8877/api'
ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = [
    {'name': 'beginner', 'topic': '单变量微积分：从函数到极限',
     'background': '只学过高中函数，对极限完全陌生。',
     'goal': '先理解函数和极限的直观含义，能完成入门题。',
     'hours_per_week': 4, 'minutes_per_session': 40, 'pretest': 'unknown'},
    {'name': 'experienced', 'topic': '单变量微积分：从函数到极限',
     'background': '已经学过函数与极限，能熟练计算简单函数值和基本极限。',
     'goal': '复核基础后深入理解连续性、导数和证明条件。',
     'hours_per_week': 6, 'minutes_per_session': 60, 'pretest': 'reference'},
    {'name': 'time_constrained', 'topic': '单变量微积分：从函数到极限',
     'background': '记得函数基本概念，但极限和连续性经常混淆。',
     'goal': '两周内掌握考试常见极限问题，优先补齐必要先修。',
     'hours_per_week': 1, 'minutes_per_session': 15, 'pretest': 'unknown'},
]


def wait_task(client: httpx.Client, task_id: str) -> dict:
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        task = client.get(f'{BASE}/tasks/{task_id}').json()
        if task['status'] in ('completed', 'failed'):
            return task
        time.sleep(1.5)
    return {'status': 'timeout', 'error': 'Task did not finish within five minutes.'}


def ask(client: httpx.Client, path: str, data: dict) -> dict:
    data['request_id'] = uuid.uuid4().hex
    response = client.post(f'{BASE}{path}', json=data)
    response.raise_for_status()
    return wait_task(client, response.json()['task_id'])


def main() -> int:
    target = ROOT / 'evidence' / ('acceptance-deepseek-synthetic.json' if '--deepseek' in sys.argv
                                  else 'acceptance-live-synthetic.json')
    previous = json.loads(target.read_text(encoding='utf-8')) if target.exists() else {}
    previous_by_name = {s['name']: s for s in previous.get('scenarios', [])}
    results = {'kind': 'live_synthetic_learner_acceptance',
               'timestamp': datetime.now(timezone.utc).isoformat(),
               'note': 'Synthetic personas and reference answers are functional tests, not human learning outcomes.',
               'scenarios': []}
    with httpx.Client(timeout=30, trust_env=False) as client:
        status = client.get(f'{BASE}/status').json()
        if not status['configured']:
            print('Local server has no real model provider configured.', file=sys.stderr)
            return 2
        # 1.2.0 requires an account; courses are created under it like a browser user.
        import getpass
        login = client.post(f'{BASE}/auth/login', json={
            'username': os.environ.get('ZHIXING_USER') or input('知行账号用户名：').strip(),
            'password': getpass.getpass('密码（不显示）：')})
        if login.status_code != 200:
            print('Login failed; synthetic scenarios were not run.', file=sys.stderr)
            return 2
        for scenario in SCENARIOS:
            name = scenario['name']
            payload = {k: v for k, v in scenario.items() if k not in ('name', 'pretest')}
            payload['search_web'] = False
            entry = previous_by_name.get(name, {'name': name, 'profile': payload})
            if entry.get('diagnostic_status') == 'completed':
                results['scenarios'].append(entry)
                continue
            course_id = entry.get('course_id')
            if not course_id:
                print(f'{name}: creating course', flush=True)
                created = ask(client, '/courses', payload)
                entry['create_status'] = created['status']
                if created['status'] != 'completed':
                    entry['error'] = created.get('error')
                    results['scenarios'].append(entry)
                    continue
                course_id = created['result']['course_id']
            entry['course_id'] = course_id
            course = client.get(f'{BASE}/courses/{course_id}').json()
            for _ in range(3):
                if not course.get('clarifications'):
                    break
                print(f'{name}: answering one clarification round', flush=True)
                clarified = ask(client, f'/courses/{course_id}/clarify',
                                {'answers': scenario['background'] + ' 请用实际前测判断我的掌握情况。'})
                if clarified['status'] != 'completed':
                    entry['clarification_error'] = clarified.get('error')
                    break
                course = client.get(f'{BASE}/courses/{course_id}').json()
            if course.get('clarifications'):
                entry['error'] = 'Clarification loop did not end after three rounds.'
                entry['events'] = [{k: event.get(k) for k in ('agent', 'provider', 'model', 'prompt_version',
                                                               'usage', 'estimated_cost_cny', 'elapsed_ms')}
                                   for event in course.get('trace', [])]
                results['scenarios'].append(entry)
                continue
            entry['diagnostic_question_count'] = len(course['diagnostic']['questions'])
            private_questions = {}
            if scenario['pretest'] == 'reference':
                trace = client.get(f'{BASE}/teacher/courses/{course_id}/trace').json()['trace']
                for event in trace:
                    if event['agent'] == 'diagnostic':
                        private_questions = {q['id']: q for q in event['output']['questions']}
            answers = [{'question_id': q['id'],
                        'answer': private_questions.get(q['id'], {}).get('expected_answer', '不知道')}
                       for q in course['diagnostic']['questions']]
            if course.get('diagnostic_result') and course['status'] != 'diagnostic':
                diagnosed = {'status': 'completed'}
            else:
                print(f'{name}: grading diagnostic and preparing lesson', flush=True)
                diagnosed = ask(client, f'/courses/{course_id}/diagnostic', {'answers': answers})
            course = client.get(f'{BASE}/courses/{course_id}').json()
            if diagnosed['status'] == 'completed' and (not course.get('lesson') or not course.get('assignment')):
                print(f'{name}: completing interrupted lesson', flush=True)
                diagnosed = ask(client, f'/courses/{course_id}/lesson', {'mode': 'continue'})
            entry['diagnostic_status'] = diagnosed['status']
            if diagnosed['status'] != 'completed':
                entry['error'] = diagnosed.get('error')
            else:
                entry.pop('error', None)
            course = client.get(f'{BASE}/courses/{course_id}').json()
            if diagnosed['status'] == 'completed' and (not course.get('lesson') or not course.get('assignment')):
                entry['diagnostic_status'] = 'failed'
                entry['error'] = 'Lesson or assignment missing after completed task.'
            entry['diagnostic_score'] = (course.get('diagnostic_result') or {}).get('score')
            entry['mastery'] = {k: v['status'] for k, v in course.get('mastery', {}).items()}
            entry['plan'] = course.get('plan')
            entry['current_unit_id'] = course.get('current_unit_id')
            entry['lesson_created'] = bool(course.get('lesson'))
            entry['assignment_count'] = len((course.get('assignment') or {}).get('questions', []))
            entry['events'] = [{k: event.get(k) for k in ('agent', 'provider', 'model', 'prompt_version',
                                                           'usage', 'estimated_cost_cny', 'elapsed_ms')}
                               for event in course.get('trace', [])]
            results['scenarios'].append(entry)
            print(f'{name}: {diagnosed["status"]}', flush=True)
    target.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Evidence saved: {target}', flush=True)
    return 0 if all(s.get('diagnostic_status') == 'completed' for s in results['scenarios']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
