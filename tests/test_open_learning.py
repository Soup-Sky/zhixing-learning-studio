import copy

import pytest

from learning.db import Store
from learning.engine import Engine, public_course


class WorkspaceGateway:
    def __init__(self):
        self.calls = []

    async def call(self, role, payload, schema):
        self.calls.append((role, copy.deepcopy(payload)))
        if role == 'teaching':
            raw = {'title': payload['unit']['title'], 'body': '认识 $x^2$ 的变化。',
                   'examples': [{'question':'观察 $x^2$', 'solution':'比较函数值'}], 'misconceptions': [], 'citations': ['s']}
        elif role == 'assignment':
            raw = {'questions': [{'id': payload['unit']['id']+'-q', 'unit_id': payload['unit']['id'],
                'kind': 'open', 'prompt': '说明变化规律', 'expected_answer': 'PRIVATE_REFERENCE',
                'solution': 'PRIVATE_SOLUTION', 'rubric': [{'criterion': '概念清楚', 'points': 1}],
                'source_ids': ['s']}]}
        elif role == 'chat':
            raw = {'reply': '根据你上次的解释，先区分函数值与变化率。', 'citations': ['s'],
                   'needs_human_review': True}
        elif role == 'grading':
            raw = {'items': [{'question_id': q['id'], 'score': 1, 'feedback': '说明完整',
                   'evidence': '量规对照', 'error_type': 'none', 'needs_human_review': False}
                   for q in payload['questions']], 'explanation': '按量规完整作答。'}
        else:
            raise AssertionError(role)
        return schema.model_validate(raw), {'provider': 'OFFLINE_FIXTURE', 'model': 'fixture'}


def setup_engine(tmp_path, status='active'):
    db = Store(tmp_path/'open.sqlite')
    db.put('sources', 's', {'id': 's', 'title': '离线参考', 'text': '定义域与函数变化'})
    c = {'id': 'c', 'topic': '函数', 'title': '函数', 'status': status, 'profile': {},
         'current_unit_id': 'u1', 'units': [
            {'id':'u1', 'title':'函数', 'prerequisites':[], 'objectives':['认识函数'], 'content':'基础笔记'},
            {'id':'u2', 'title':'变化', 'prerequisites':['u1'], 'objectives':['理解变化']},
            {'id':'u3', 'title':'应用', 'prerequisites':['u2'], 'objectives':['应用函数']}],
         'plan': {'unit_order': ['u1','u2']}, 'mastery':{}, 'history':[], 'trace':[],
         'source_ids':['s'], 'lesson':None, 'assignment':None}
    db.put('courses','c',c)
    return Engine(db, WorkspaceGateway())


@pytest.mark.parametrize('status', ['active','diagnostic'])
async def test_any_graph_unit_can_be_learned_without_certifying_prerequisites(tmp_path, status):
    e = setup_engine(tmp_path, status)
    await e.lesson('c', {'unit_id':'u3', 'mode':'review'})
    saved = e.db.get('courses','c')
    assert saved['assignment']['unit_id'] == 'u3'
    assert saved['mastery'] == {}
    if status == 'diagnostic':
        assert saved['status'] == 'diagnostic'
    payload = e.gateway.calls[0][1]
    assert payload['prerequisite_evidence'][0]['unit_id'] == 'u2'
    assert payload['prerequisite_evidence'][0]['status'] == 'unknown'


async def test_switching_units_preserves_original_assignment_and_read_only_workspace(tmp_path):
    e = setup_engine(tmp_path)
    await e.lesson('c', {'unit_id':'u1'})
    original = copy.deepcopy(e.db.get('courses','c')['assignment'])
    await e.lesson('c', {'unit_id':'u2'})
    before = e.db.get('courses','c')
    view = e.workspace('c','u1')
    assert view['assignment']['id'] == original['id']
    assert 'PRIVATE_REFERENCE' not in str(view)
    assert 'PRIVATE_SOLUTION' not in str(view)
    assert 'PRIVATE_REFERENCE' not in str(public_course(before))
    assert e.db.get('courses','c') == before
    assert e.workspace('c','u3')['lesson'] is None
    assert e.workspace('c','u1')['unit']['content'] == '基础笔记'


async def test_cached_lesson_revisit_does_not_regenerate_or_erase_draft_assignment(tmp_path):
    e = setup_engine(tmp_path)
    await e.lesson('c', {'unit_id':'u1'})
    original_id = e.db.get('courses','c')['assignment']['id']
    await e.lesson('c', {'unit_id':'u2'})
    calls = len(e.gateway.calls)
    await e.lesson('c', {'unit_id':'u1', 'mode':'review'})
    assert len(e.gateway.calls) == calls
    assert e.db.get('courses','c')['assignment']['id'] == original_id


async def test_ai_reviewed_full_score_does_not_prevent_learning_next_unit(tmp_path):
    e = setup_engine(tmp_path)
    await e.lesson('c', {'unit_id':'u1'})
    assignment = e.db.get('courses','c')['assignment']
    await e.lesson('c', {'unit_id':'u2'})
    result = await e.submit('c', {'assignment_id':assignment['id'], 'request_id':'grade',
                                 'answers':[{'question_id':'u1-q','answer':'自己的解释'}]})
    assert result['score'] == 1 and result['needs_human_review'] is False
    assert e.db.get('courses','c')['mastery']['u1']['status'] == 'mastered'
    assert e.workspace('c','u1')['assignment']['submitted']
    assert e.workspace('c','u2')['assignment']['unit_id'] == 'u2'
    assert e.db.get('courses','c')['last_feedback']['decision'] in ('advance', 'complete')


async def test_selection_chat_uses_viewed_unit_mastery_and_actual_feedback_without_answer_keys(tmp_path):
    e = setup_engine(tmp_path)
    await e.lesson('c', {'unit_id':'u1'})
    original = e.db.get('courses','c')['assignment']
    await e.submit('c', {'assignment_id':original['id'], 'request_id':'submit',
                        'answers':[{'question_id':'u1-q','answer':'说明变化'}]})
    await e.lesson('c', {'unit_id':'u2'})
    await e.chat('c', {'unit_id':'u1', 'message':'为什么这样？', 'selected_text':'函数的定义域',
                       'surrounding_text':'分母不能为零', 'request_id':'ask'})
    role, payload = e.gateway.calls[-1]
    assert role == 'chat'
    assert payload['unit']['id'] == 'u1'
    assert payload['selection']['text'] == '函数的定义域'
    assert payload['selection']['context'] == '分母不能为零'
    assert payload['mastery']['u1']['status'] == 'mastered'
    assert payload['recent_feedback'][0]['score'] == 1
    assert 'PRIVATE_REFERENCE' not in str(payload)
    assert 'PRIVATE_SOLUTION' not in str(payload)
    assert e.workspace('c','u1')['messages'][-1]['role'] == 'assistant'


async def test_unknown_unit_is_rejected_before_provider_call(tmp_path):
    e = setup_engine(tmp_path)
    with pytest.raises(ValueError):
        await e.chat('c', {'unit_id':'unknown', 'message':'解释', 'request_id':'r'})
    assert e.gateway.calls == []
