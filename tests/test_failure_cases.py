"""Teacher's seven failure classes, two executable regressions per class.

These are injected adversarial outputs, not measured provider failure rates.
Semantic falsehoods are contained by review, not claimed to be detected as false.
"""
import copy

import pytest

from learning.db import Store
from learning.engine import Engine


def question(**changes):
    q = dict(id='q', prompt='计算 f(x)=x² 在 x=1 处的导数', kind='expression',
             unit_id='u1', expected_answer='2', solution='2x 在1处为2',
             rubric=[{'criterion': '结果', 'points': 1}], variables=['x'], domain='real',
             verification={'type': 'value', 'expression': '2*x', 'point': '1', 'expected': '2'},
             validation={'status': 'verified'}, source_ids=['s'])
    q.update(changes)
    return q


def course():
    return dict(id='c', status='active', topic='极限', current_unit_id='u1', profile={},
                units=[{'id': 'u1', 'title': '极限', 'prerequisites': []},
                       {'id': 'u2', 'title': '导数', 'prerequisites': ['u1']}],
                plan={'unit_order': ['u1', 'u2']}, mastery={}, history=[], trace=[],
                source_ids=['s'], assignment={'id': 'a', 'unit_id': 'u1', 'questions': [question()]})


class AdversarialGateway:
    def __init__(self, score=1, body='示例讲义', citations=None):
        self.score, self.body = score, body
        self.citations = ['s'] if citations is None else citations

    async def call(self, role, payload, schema):
        if role == 'grading':
            raw = {'items': [dict(question_id=q['id'], score=self.score, feedback='模型声称确定',
                                 evidence='未提供可靠证据', error_type='unknown', needs_human_review=False)
                             for q in payload['questions']], 'explanation': '注入的过度自信评分'}
        elif role == 'teaching':
            raw = dict(title='含错误的讲义', body=self.body, examples=[{'question': '示例', 'solution': '答案'}],
                       misconceptions=[], citations=self.citations, needs_human_review=False)
        elif role == 'assignment':
            raw = {'questions': [question()]}
        elif role == 'planning':
            raw = dict(unit_order=['u1', 'u2'], reason='连续未达标，先补讲当前单元', weekly_hours=2,
                       sessions=[{'unit_id': 'u1', 'minutes': 30, 'focus': '针对错因补讲'},
                                 {'unit_id': 'u2', 'minutes': 20, 'focus': '通过先修后再学习'}], goal='完成极限学习')
        else:
            raise AssertionError(role)
        return schema.model_validate(raw), {'provider': 'TEST_ONLY', 'model': 'adversarial_fixture', 'usage': {}}


def engine(tmp_path, gateway=None):
    db = Store(tmp_path / 'failure.sqlite')
    db.put('courses', 'c', course())
    db.put('sources', 's', {'id': 's', 'title': '来源占位仅用于引用边界', 'text': ''})
    return Engine(db, gateway or AdversarialGateway())


@pytest.mark.parametrize('body,citations', [
    ('极限第三定理：任何函数在任何点都有极限。', []),
    ('所有连续函数都可导。', ['s']),
])
async def test_f1_fabricated_theorem_is_flagged_with_ai_advice(tmp_path, body, citations):
    e = engine(tmp_path, AdversarialGateway(body=body, citations=citations))
    await e.lesson('c', {'mode': 'continue'})
    c = e.db.get('courses', 'c')
    assert c['lesson']['needs_human_review'] is False
    assert c['lesson']['ai_review']['verdict'] in ('accepted', 'uncertain')
    assert any(r['kind'] == 'lesson' and r['status'] == 'ai_reviewed' for r in e.db.list('reviews'))


@pytest.mark.parametrize('spec,wrong', [
    ({'type': 'derivative', 'expression': 'x**2', 'variable': 'x'}, '3*x'),
    ({'type': 'integral', 'expression': 'x', 'lower': '0', 'upper': '1'}, '1'),
])
async def test_f2_wrong_derivation_answer_rejected(tmp_path, spec, wrong):
    e = engine(tmp_path)
    with pytest.raises(ValueError, match='独立答案核验'):
        await e.validate_questions([question(verification=spec, expected_answer=wrong)], {'u1'})


@pytest.mark.parametrize('unit_id', ['u2', 'nonexistent'])
async def test_f3_out_of_scope_assignment_rejected(tmp_path, unit_id):
    e = engine(tmp_path)
    with pytest.raises(ValueError, match='范围'):
        await e.validate_questions([question(unit_id=unit_id)], {'u1'})


@pytest.mark.parametrize('q', [
    question(prompt='求函数极限', verification={}),
    question(prompt='给出一个导数为2x的原函数', kind='open', expected_answer='x**2+C', verification={}),
])
async def test_f4_underspecified_or_nonunique_question_gets_ai_advice(tmp_path, q):
    result = await engine(tmp_path).validate_questions([copy.deepcopy(q)], {'u1'})
    assert result[0]['needs_human_review'] is False
    assert result[0]['ai_review']['verdict'] == 'uncertain'
    assert result[0]['validation']['status'] == 'undetermined'


@pytest.mark.parametrize('expected,answer', [('3*x', 'x+2*x'), ('(x+1)**2', 'x**2+2*x+1')])
async def test_f5_equivalent_answer_overrides_incorrect_model_score(tmp_path, expected, answer):
    e = engine(tmp_path, AdversarialGateway(score=0))
    result = await e.grade(course(), [question(expected_answer=expected)], [{'question_id': 'q', 'answer': answer}])
    assert result['score'] == 1
    assert result['items'][0]['evidence']['mathematical_check']['status'] == 'verified'


@pytest.mark.parametrize('answer', ['用图像给出与参考答案不同的论证。', '题目的条件不足，给出反例。'])
async def test_f6_open_grading_advances_with_ai_uncertainty_visible(tmp_path, answer):
    e = engine(tmp_path)
    c = e.db.get('courses', 'c')
    c['assignment']['questions'][0]['kind'] = 'open'
    e.db.put('courses', 'c', c)
    r = await e.submit('c', {'assignment_id': 'a', 'answers': [{'question_id': 'q', 'answer': answer}], 'request_id': 'r'})
    assert r['needs_human_review'] is False and r['decision'] in ('advance', 'complete', 'remedial')
    assert r['ai_uncertain'] is True
    assert e.db.get('courses', 'c')['mastery']['u1']['status'] in ('mastered', 'learning')


@pytest.mark.parametrize('answer', ['7', '-2'])
async def test_f7_repeated_errors_recommend_remediation_without_certifying_next_unit(tmp_path, answer):
    e = engine(tmp_path)
    for n in range(3):
        c = e.db.get('courses', 'c')
        c['assignment'].update(id=f'a{n}', submitted=False)
        e.db.put('courses', 'c', c)
        r = await e.submit('c', {'assignment_id': f'a{n}', 'answers': [{'question_id': 'q', 'answer': answer}], 'request_id': str(n)})
        assert r['decision'] == 'remedial' and r['next_unit_id'] == 'u1'
    assert e.db.get('courses', 'c')['mastery']['u1']['failures'] == 3
    with pytest.raises(ValueError, match='范围'):
        # This adversarial fixture deliberately supplies the old unit's question.
        # Free browsing must not publish an assignment belonging to another unit.
        await e.lesson('c', {'mode': 'continue', 'unit_id': 'u2'})


class FiveRoleFixture(AdversarialGateway):
    async def call(self, role, payload, schema):
        if role == 'diagnostic':
            raw = dict(summary='离线诊断夹具，无真人测量', clarifications=[], strengths=[], unknowns=['尚无作答'],
                       units=[{'id': 'u1', 'title': '起点', 'prerequisites': []},
                              {'id': 'u2', 'title': '后续', 'prerequisites': ['u1']}], questions=[question()])
        elif role == 'planning':
            raw = dict(unit_order=['u1', 'u2'], reason='根据传入诊断结果保留未测单元', weekly_hours=2,
                       sessions=[{'unit_id': 'u1', 'minutes': 20, 'focus': '基础'}, {'unit_id': 'u2', 'minutes': 20, 'focus': '后续'}], goal='完成测试')
        else:
            return await super().call(role, payload, schema)
        return schema.model_validate(raw), {'provider': 'TEST_ONLY', 'model': 'five_role_fixture', 'usage': {}}


async def test_complete_five_role_loop_with_actual_engine_and_injected_provider(tmp_path):
    e = engine(tmp_path, FiveRoleFixture())
    result = await e.create({'topic': '基础代数', 'goal': '完成测试', 'background': '未知',
                             'hours_per_week': 2, 'minutes_per_session': 20, 'preference': '例题',
                             'source_ids': ['s'], 'search_web': False})
    cid = result['course_id']
    await e.diagnose(cid, {'answers': [{'question_id': 'q', 'answer': '2'}]})
    c = e.db.get('courses', cid)
    feedback = await e.submit(cid, {'assignment_id': c['assignment']['id'],
                                    'answers': [{'question_id': 'q', 'answer': '4/2'}], 'request_id': 'loop'})
    c = e.db.get('courses', cid)
    assert [t['agent'] for t in c['trace']] == ['diagnostic', 'grading', 'planning', 'teaching', 'assignment', 'grading']
    assert c['trace'][2]['input']['learner']['diagnostic_evidence']['score'] == 1
    assert c['trace'][4]['input']['lesson']['body'] == c['lesson']['body']
    assert feedback['decision'] == 'advance' and feedback['next_unit_id'] == 'u2'
    assert c['lesson']['needs_human_review'] is False
    assert c['lesson']['ai_review']['verdict'] in ('accepted', 'uncertain')


@pytest.mark.parametrize('hours', [3, 2.5, 3.5])
async def test_create_accepts_default_and_fractional_weekly_hours(tmp_path, hours):
    e = engine(tmp_path, FiveRoleFixture())
    result = await e.create({'topic': '基础代数', 'goal': '完成测试', 'background': '未知',
                             'hours_per_week': hours, 'minutes_per_session': 20, 'preference': '例题',
                             'source_ids': ['s'], 'search_web': False})
    saved = e.db.get('courses', result['course_id'])
    assert saved['profile']['hours_per_week'] == hours


class PlanWithoutGoal(FiveRoleFixture):
    async def call(self, role, payload, schema):
        if role == 'planning':
            raw = dict(unit_order=['u1', 'u2'], reason='根据传入诊断结果保留未测单元', weekly_hours=2,
                       sessions=[{'unit_id': 'u1', 'minutes': 20, 'focus': '基础'}])
            return schema.model_validate(raw), {'provider': 'TEST_ONLY', 'model': 'no_goal_fixture', 'usage': {}}
        return await super().call(role, payload, schema)


async def test_plan_missing_goal_uses_learner_goal(tmp_path):
    e = engine(tmp_path, PlanWithoutGoal())
    cid = (await e.create({'topic': '机器学习', 'goal': '把实际问题转化为机器学习任务', 'background': '零基础',
                           'source_ids': ['s'], 'search_web': False}))['course_id']
    await e.diagnose(cid, {'answers': [{'question_id': 'q', 'answer': '2'}]})
    c = e.db.get('courses', cid)
    assert c['status'] == 'active' and c['plan']['goal'] == '把实际问题转化为机器学习任务'


class PlanningFailsOnce(FiveRoleFixture):
    failed = False

    async def call(self, role, payload, schema):
        if role == 'planning' and not self.failed:
            self.failed = True
            from learning.provider import ProviderFailure
            raise ProviderFailure('DeepSeek 返回格式校验失败（已尝试一次修复）。')
        return await super().call(role, payload, schema)


async def test_failed_planning_retries_with_empty_answers_without_regrading(tmp_path):
    from learning.provider import ProviderFailure
    e = engine(tmp_path, PlanningFailsOnce())
    cid = (await e.create({'topic': '基础代数', 'goal': 'g', 'source_ids': ['s'], 'search_web': False}))['course_id']
    with pytest.raises(ProviderFailure):
        await e.diagnose(cid, {'answers': [{'question_id': 'q', 'answer': '2'}]})
    assert e.db.get('courses', cid)['status'] == 'diagnostic'
    # The page's "继续规划课程" button sends no answers; the saved grading is reused.
    await e.diagnose(cid, {'answers': []})
    c = e.db.get('courses', cid)
    assert c['status'] == 'active'
    assert [t['agent'] for t in c['trace']].count('grading') == 1
