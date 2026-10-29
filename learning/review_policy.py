"""One place that decides how AI uncertainty is labelled.

Default mode is AI auto-review: uncertainty never blocks learning. Uncertain items
carry ``ai_uncertain`` and an advice record, and they appear in the teacher review
channel where an administrator may confirm or correct them. ``needs_human_review``
stays False because no human is required before the learner continues.
"""
from __future__ import annotations

ACCEPTED = 'accepted'
UNCERTAIN = 'uncertain'


def ai_review(uncertain: bool, advice_ok: str, advice_uncertain: str, issues=None) -> dict:
    return {'verdict': UNCERTAIN if uncertain else ACCEPTED,
            'advice': advice_uncertain if uncertain else advice_ok,
            'issues': list(issues or (['需要结合上下文核对'] if uncertain else []))}


def mark(target: dict, uncertain: bool, advice_ok: str, advice_uncertain: str, issues=None) -> dict:
    """Stamp a lesson, question, grade item or reply with the shared review fields."""
    target['needs_human_review'] = False
    target['ai_uncertain'] = bool(uncertain)
    target['ai_review'] = ai_review(uncertain, advice_ok, advice_uncertain, issues)
    return target


def question_uncertain(validation: dict) -> bool:
    return validation.get('status') != 'verified'


def grade_item_uncertain(question: dict, check: dict, model_flag: bool) -> bool:
    trusted = question.get('validation', {}).get('status') == 'verified'
    return (not trusted or check.get('status') == 'undetermined' or bool(model_flag)
            or question.get('kind') == 'open')


def legacy_status(record: dict, advice: str, issue: str) -> dict:
    """Older snapshots used a blocking human-review label; show them as AI-reviewed advice."""
    if record.get('review_status') not in ('approved', 'ai_reviewed', 'teacher_reviewed'):
        record['review_status'] = 'ai_reviewed'
        record.setdefault('ai_review', {'verdict': UNCERTAIN, 'advice': advice, 'issues': [issue]})
    return record


def review_record(course_id: str, kind: str, reason: str, content: dict, *, record_id: str, created_at: str,
                  uncertain: bool = True, **extra) -> dict:
    """An audit entry. ``teacher_status`` drives the optional teacher review channel."""
    return {'id': record_id, 'course_id': course_id, 'kind': kind, 'reason': reason,
            'status': 'ai_reviewed', 'review_mode': 'ai', 'content': content, 'created_at': created_at,
            'teacher_status': 'open' if uncertain else 'none',
            'ai_review': ai_review(uncertain, reason, reason, None if uncertain else []), **extra}


def public_review(record: dict) -> dict:
    """Learner-facing view: never the stored content, which may hold answer keys."""
    keys = ('id', 'kind', 'reason', 'status', 'review_mode', 'ai_review', 'created_at', 'teacher_status', 'teacher_review',
            'history_id', 'question_id')
    return {k: record[k] for k in keys if k in record}
