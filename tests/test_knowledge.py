from learning.knowledge import builtin_course


def test_twelve_unit_graph_and_meaningful_bank():
    course = builtin_course()
    assert len(course['units']) == 12
    assert len(course['questions']) >= 36
    seen = set()
    for unit in course['units']:
        assert set(unit['prerequisites']) <= seen
        assert len(unit['content']) > 150
        assert unit['review_status'] == 'ai_reviewed'
        assert unit['ai_review']['verdict'] == 'uncertain'
        seen.add(unit['id'])
    assert len({q['prompt'] for q in course['questions']}) == len(course['questions'])
    assert all(q['solution'] and q['rubric'] and q['expected_answer'] for q in course['questions'])
    assert all(s['url'].startswith('https://') and s['locator'] and s['license'] for s in course['sources'])


def test_independent_loads():
    a = builtin_course()
    a['units'].clear()
    assert len(builtin_course()['units']) == 12


def test_every_expression_key_has_independent_verification():
    from learning.mathcheck import verify_problem
    for question in builtin_course()['questions']:
        if question['kind']=='expression':
            assert question.get('verification'),question['id']
            assert verify_problem(question)['status']=='verified',question['id']


def test_builtin_notes_keep_their_honest_review_label():
    course = builtin_course()
    assert all('未经教师审定' in u['content'] for u in course['units'] if '原创笔记' in u['content'])
    assert not any('由 AI 自动审核' in u['content'] for u in course['units'])
