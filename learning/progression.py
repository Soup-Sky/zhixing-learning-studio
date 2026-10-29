"""Knowledge-graph progression: the graph, not the model, decides order and mastery."""
from __future__ import annotations
import copy
from datetime import datetime, timezone, timedelta

MASTERY = 0.8
# Spaced review intervals in days, counted from the moment of each successful review.
REVIEW_DAYS = (1, 3, 7)


def validate_graph(units):
    by = {u['id']: u for u in units}
    if len(by) != len(units) or not units: raise ValueError('课程单元ID重复或课程为空。')
    visited = set(); stack = set(); order = []

    def visit(id):
        if id not in by: raise ValueError('课程引用了不存在的先修知识。')
        if id in stack: raise ValueError('课程先修关系存在循环。')
        if id in visited: return
        stack.add(id)
        for p in by[id].get('prerequisites', []): visit(p)
        stack.remove(id); visited.add(id); order.append(id)
    for id in by: visit(id)
    return order


def with_prerequisites(units, planned):
    """All transitive prerequisites of the planned units, each visited once."""
    by = {u['id']: u for u in units}
    seen = set(); missing = set()

    def include(id):
        if id in seen: return
        seen.add(id)
        for p in by[id].get('prerequisites', []):
            if p not in planned: missing.add(p)
            include(p)
    for id in list(planned): include(id)
    return missing


def next_unit(c):
    order = c.get('plan', {}).get('unit_order') or validate_graph(c['units'])
    for id in order:
        if c['mastery'].get(id, {}).get('status') != 'mastered': return id
    return None


def due_after(stage, at=None):
    """Next review time after reaching ``stage`` successful reviews; None once finished."""
    if stage >= len(REVIEW_DAYS): return None
    return ((at or datetime.now(timezone.utc)) + timedelta(days=REVIEW_DAYS[stage])).isoformat()


def recompute(c):
    order = validate_graph(c['units'])
    mastery = {id: {'status': 'unknown', 'score': None, 'failures': 0, 'evidence': []} for id in order}
    for id, value in c.get('diagnostic_mastery', {}).items():
        if id in mastery: mastery[id] = copy.deepcopy(value)
    for h in c['history']:
        m = mastery[h['unit_id']]; f = h['feedback']
        m['evidence'].append(h['id']); m['score'] = f['score']
        if f['score'] >= MASTERY:
            m['status'] = 'mastered'; m['failures'] = 0
            if f.get('ai_review', {}).get('verdict') == 'uncertain' or f.get('ai_uncertain'):
                m['ai_confidence'] = 'uncertain'; m['ai_advice'] = f.get('ai_review', {}).get('advice', '建议复习本题反馈。')
            else: m['ai_confidence'] = 'accepted'
        else: m['status'] = 'learning'; m['failures'] += 1
    # AI uncertainty remains visible as evidence, but never blocks browsing or later units.
    by = {u['id']: u for u in c['units']}
    for id in order:
        if mastery[id]['status'] == 'mastered' and any(mastery[p]['status'] != 'mastered' for p in by[id].get('prerequisites', [])):
            mastery[id]['status'] = 'learning'; mastery[id]['blocked_by_prerequisite'] = True
    c['mastery'] = mastery
    if not c['history']: return
    f = copy.deepcopy(c['history'][-1]['feedback']); unit = c['history'][-1]['unit_id']
    nextid = next_unit(c)
    # Practice before the pretest must not end the diagnostic stage.
    keep = c.get('status') == 'diagnostic' and not c.get('plan')
    if nextid is None:
        f['decision'] = 'complete'
        if not keep: c['status'] = 'completed'
    elif mastery[unit]['status'] == 'mastered':
        f['decision'] = 'advance'
        if not keep: c['status'] = 'active'
    else:
        f['decision'] = 'remedial'
        if not keep: c['status'] = 'active'
        f['explanation'] += ' 连续两次未达标，需针对性补讲、更换解释并重新规划补救练习。' if mastery[unit]['failures'] >= 2 else ' 请完成针对性补讲和练习。'
    f['next_unit_id'] = nextid; c['last_feedback'] = f
