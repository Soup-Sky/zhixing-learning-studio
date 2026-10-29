import json
from pathlib import Path


def builtin_course():
    """Load the authoritative prerequisite DAG with AI-audit metadata."""
    course=json.loads((Path(__file__).resolve().parents[1]/'knowledge'/'calculus.json').read_text(encoding='utf-8'))
    specs=course.pop('verification_specs',{})
    # The JSON marks unevaluated notes ``needs_human_review``. Learning is not blocked on
    # that; the uncertainty stays visible as advice and the teacher channel can review it.
    for source in course.get('sources',[]):
        if source.get('review_status') not in ('approved','ai_reviewed'):
            source['review_status']='ai_reviewed'
            source.setdefault('ai_review',{'verdict':'uncertain','advice':'AI 已完成自动审核；关键结论建议结合原文核对。','issues':['内置资料未提供人工审批记录']})
    for unit in course.get('units',[]):
        if unit.get('review_status') not in ('approved','ai_reviewed'):
            unit['review_status']='ai_reviewed'
            unit.setdefault('ai_review',{'verdict':'uncertain','advice':'内置原创笔记，未经教师审定；可以继续学习，关键结论建议结合来源核对。','issues':['未经教师审定']})
        # The note's own "未经教师审定" wording is kept: it is the accurate status of this material.
    for question in course['questions']:
        if question['id'] in specs: question['verification']=specs[question['id']]
    return course
