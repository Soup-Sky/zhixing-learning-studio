import pytest

from learning.engine import Engine
from learning.db import Store


class UncertainGateway:
    async def call(self, role, payload, schema):
        if role == 'teaching':
            raw = {
                'title': 'AI 讲解',
                'body': '讲解内容',
                'examples': [{'question': '例题', 'solution': '解法'}],
                'misconceptions': [],
                'citations': [],
                'needs_human_review': True,
            }
        elif role == 'assignment':
            raw = {'questions': [{
                'id': 'q1', 'unit_id': 'u1', 'kind': 'open', 'prompt': '解释概念',
                'expected_answer': '核心概念', 'solution': '参考解法',
                'rubric': [{'criterion': '说明清楚', 'points': 1}], 'source_ids': [],
            }]}
        elif role == 'grading':
            raw = {'items': [{
                'question_id': 'q1', 'score': 1, 'feedback': '回答完整',
                'evidence': '开放题量规', 'error_type': 'none',
                'needs_human_review': True,
            }], 'explanation': 'AI 已完成自动评分，但置信度有限。'}
        else:
            raise AssertionError(role)
        return schema.model_validate(raw), {'provider': 'TEST_ONLY', 'model': 'uncertain'}


def make_engine(tmp_path):
    db = Store(tmp_path / 'ai-review.sqlite')
    db.put('sources', 's', {'id': 's', 'title': '本地资料', 'text': '内容'})
    db.put('courses', 'c', {
        'id': 'c', 'title': '测试', 'topic': '函数', 'status': 'active',
        'profile': {}, 'current_unit_id': 'u1',
        'units': [{'id': 'u1', 'title': '函数', 'prerequisites': []}],
        'plan': {'unit_order': ['u1']}, 'mastery': {}, 'history': [], 'trace': [],
        'source_ids': ['s'], 'lesson': None, 'assignment': None,
    })
    return Engine(db, UncertainGateway())


@pytest.mark.asyncio
async def test_ai_uncertainty_is_advice_and_does_not_block_progress(tmp_path):
    engine = make_engine(tmp_path)
    await engine.lesson('c', {'mode': 'continue'})
    course = engine.db.get('courses', 'c')
    assert course['lesson']['needs_human_review'] is False
    assert course['lesson']['ai_review']['verdict'] == 'uncertain'
    assert all(review['status'] != 'pending' for review in engine.db.list('reviews'))

    result = await engine.submit('c', {
        'assignment_id': course['assignment']['id'],
        'answers': [{'question_id': 'q1', 'answer': '自己的解释'}],
        'request_id': 'submit-1',
    })
    updated = engine.db.get('courses', 'c')
    assert result['decision'] == 'complete'
    assert result['needs_human_review'] is False
    assert result['ai_review']['verdict'] == 'uncertain'
    assert updated['mastery']['u1']['status'] == 'mastered'
    assert all(review['status'] != 'pending' for review in engine.db.list('reviews'))


def test_ai_review_records_are_completed_audit_entries(tmp_path):
    engine = make_engine(tmp_path)
    record = engine.review(engine.db.get('courses', 'c'), 'lesson', '自动检查', {})
    assert record['review_mode'] == 'ai'
    assert record['status'] == 'ai_reviewed'
