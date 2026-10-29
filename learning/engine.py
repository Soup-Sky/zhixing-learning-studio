"""Five-agent teaching, evidence-based progression and reversible teacher decisions."""
from __future__ import annotations
import asyncio
import copy
import math
import re
from .db import Store,uid,now
from .schemas import Diagnostic,Plan,Lesson,Assignment,Grade,Reply,Question
from .provider import redact
from . import review_policy as rp
from .progression import validate_graph, with_prerequisites, due_after, MASTERY
from . import progression

TRACE_LIMIT = 200

PRIVATE = {'expected_answer','solution','verification','validation','hints'}

def public_question(q):
    return {k:v for k,v in q.items() if k not in PRIVATE}

def public_course(raw):
    c=copy.deepcopy(raw)
    c.pop('workspaces',None)
    c.pop('chat_requests',None)
    for field in ('diagnostic','assignment'):
        if c.get(field):c[field]['questions']=[public_question(q) for q in c[field].get('questions',[])]
    c.pop('question_bank',None)
    c.pop('assessment_sets',None)
    c.pop('processed',None)
    # Migrate legacy course snapshots that still carry the former human-review
    # label. Uncertainty remains visible through ai_review, never as a queue.
    for unit in c.get('units',[]):rp.legacy_status(unit,'AI 已完成自动审核；关键结论建议结合来源核对。','历史记录使用旧审核状态')
    for source in c.get('sources',[]):rp.legacy_status(source,'AI 已完成自动审核；建议结合原文核对。','历史记录使用旧审核状态')
    # Raw traces include private answer keys and source text. Students see handoff metadata.
    c['trace']=[{k:v for k,v in t.items() if k not in ('input','output')} for t in c.get('trace',[])]
    for h in c.get('history',[]):h.pop('questions',None)
    return redact(c)


def remember_workspace(c):
    unit=c.get('current_unit_id')
    if not unit:return
    existing=c.setdefault('workspaces',{}).setdefault(unit,{})
    for field in ('lesson','assignment'):
        if c.get(field) is not None:existing[field]=copy.deepcopy(c[field])

def source_context(sources):
    return [{k:s.get(k,'') for k in ('id','title','url','locator','license','review_status')}|{'text':s.get('text','')[:6000]} for s in sources[:8]]

def out_of_scope_assignment(questions, unit_id):
    # The first calculus units have a strict conceptual boundary; a model's unit_id alone is not evidence of scope.
    future = {'u01': r'极限|\blim\b|连续|导数|微分|积分',
              'u02': r'连续|导数|微分|积分',
              'u03': r'导数|微分|积分'}
    pattern = future.get(unit_id)
    return [q['id'] for q in questions if pattern and re.search(pattern, q['prompt'], re.IGNORECASE)]

class Engine:
    def __init__(self,store:Store,gateway):
        self.db=store;self.gateway=gateway

    async def call(self,c,role,payload,schema,progress=None):
        if progress:progress({'diagnostic':'分析目标与生成前测','planning':'根据前测规划课程','teaching':'检索资料并生成分层讲义','assignment':'生成与检查练习','grading':'核对答案与量规评分','chat':'结合学习记录回答追问'}.get(role,role))
        result,meta=await self.gateway.call(role,payload,schema)
        trace=c.setdefault('trace',[])
        trace.append({'id':uid(),'agent':role,'input':redact(payload),'output':result.model_dump(),'created_at':now(),'tools':[],**meta})
        # Raw traces carry whole payloads; keep the recent ones so courses do not grow without bound.
        if len(trace)>TRACE_LIMIT:del trace[:len(trace)-TRACE_LIMIT]
        return result.model_dump()

    def sources(self,c):
        result=[]
        for id in c.get('source_ids',[]):
            try:result.append(self.db.get('sources',id))
            except KeyError:pass
        return result

    def view(self,id):
        from urllib.parse import urlsplit
        from .sources import matches_search_topic
        c=self.db.get('courses',id)
        # Group display records without deleting stored evidence or citation IDs.
        grouped={}
        for source in self.sources(c):
            key=('url',urlsplit(source['url'])._replace(fragment='').geturl()) if source.get('url') else ('id',source['id'])
            if key in grouped:
                group=grouped[key]
                if source['id'] not in group['record_ids']:group['record_ids'].append(source['id'])
                rp.legacy_status(group,'AI 已完成自动审核；建议结合原文核对。','历史记录使用旧审核状态')
                continue
            source['record_ids']=[source['id']]
            if 'search_snippet' in source and source.get('review_status')!='approved' and not matches_search_topic(source,c.get('topic','')):
                source['relevance_note']='AI 未在页面正文中匹配当前主题关键词，建议结合原文自行核对相关性。'
                source['review_status']='ai_reviewed'
                source['ai_review']={'verdict':'uncertain','advice':'建议打开原文核对主题相关性。','issues':['主题关键词未匹配']}
            grouped[key]=source
        c['sources']=list(grouped.values())
        c['recommended_unit_id']=self.next_unit(c) if c.get('units') else None
        # Review evidence is teacher-only; the course view holds status, never private question content.
        c['review_items']=[rp.public_review(r) for r in self.db.list('reviews') if r.get('course_id')==id]
        return public_course(c)

    def workspace(self,id,unit_id):
        c=self.db.get('courses',id)
        by={u['id']:u for u in c['units']}
        if unit_id not in by:raise ValueError('知识单元不存在。')
        remember_workspace(c)
        cached=copy.deepcopy(c.get('workspaces',{}).get(unit_id,{}))
        assignment=cached.get('assignment')
        if assignment:assignment['questions']=[public_question(q) for q in assignment.get('questions',[])]
        history=[h for h in c.get('history',[]) if h['unit_id']==unit_id]
        order=validate_graph(c['units']);index=order.index(unit_id)
        feedback=copy.deepcopy(history[-1]['feedback']) if history else None
        if feedback and feedback.get('decision')=='review':
            feedback['decision']='advance' if feedback.get('score',0)>=0.8 else 'remedial'
        if feedback and feedback.get('ai_review',{}).get('verdict')=='uncertain':
            feedback['explanation']=(feedback.get('explanation') or '')+' AI 已完成自动审核；置信度不足的部分已标注建议，但不会阻塞后续知识点。'
        return redact({'unit':by[unit_id],'lesson':cached.get('lesson'),'assignment':assignment,
            'last_feedback':feedback,'last_history_id':history[-1]['id'] if history else None,
            'history':[{'assignment_id':h['assignment_id']} for h in history],
            'messages':[m for m in c.get('messages',[]) if m.get('unit_id',c.get('current_unit_id'))==unit_id],
            'next_unit_id':order[index+1] if index+1<len(order) else None,
            'recommended_unit_id':self.next_unit(c),
            'prerequisites':[{'unit_id':p,'title':by[p]['title'],
                             **c.get('mastery',{}).get(p,{'status':'unknown'})} for p in by[unit_id].get('prerequisites',[])]})

    async def create(self,data,progress=None,owner_id=None):
        from .knowledge import builtin_course
        from .sources import search_sources
        # owner_id stays outside profile so it is never sent to the model.
        c={'id':uid(),'owner_id':owner_id,'title':data['topic'],'topic':data['topic'],'created_at':now(),'status':'diagnostic',
           'profile':{k:v for k,v in data.items() if k not in ('source_ids','request_id')},'source_ids':list(data.get('source_ids',[])),
           'units':[],'mastery':{},'history':[],'trace':[],'processed':{},'lesson':None,'assignment':None,'current_unit_id':None,'retrieval_notes':[]}
        for id in c['source_ids']:self.db.get('sources',id)
        is_calculus=any(k in data['topic'].lower() for k in ('微积分','极限','导数','积分','calculus'))
        if is_calculus:
            builtin=builtin_course()
            c['units']=builtin['units'];c['question_bank']=builtin['questions'];c['builtin']=True
            for s in builtin['sources']:
                try:self.db.get('sources',s['id'])
                except KeyError:self.db.put('sources',s['id'],s)
                if s['id'] not in c['source_ids']:c['source_ids'].append(s['id'])
        if data.get('search_web',True):
            if progress:progress('检索公开教学资料，保留来源与提取结果')
            try:
                found=await search_sources(data['topic']+' university tutorial',limit=3)
                for s in found:s['owner_id']=owner_id;self.db.put('sources',s['id'],s);c['source_ids'].append(s['id'])
                if not found:c['retrieval_notes'].append('未检索到可提取正文的资料，可上传或添加网址。')
            except Exception:c['retrieval_notes'].append('公开检索暂不可用；已保留上传和内置资料，可稍后添加来源。')
        payload={'learner':c['profile'],'known_units':c['units'],'sources':source_context(self.sources(c))}
        diagnostic=await self.call(c,'diagnostic',payload,Diagnostic,progress)
        if not c['units']:c['units']=diagnostic['units']
        order=validate_graph(c['units'])
        if len(c['units'])>20:raise ValueError('首期课程应分为不超过20个单元，请缩小学习主题。')
        allowed=set(order)
        for q in diagnostic['questions']:
            if q['unit_id'] not in allowed:raise ValueError('诊断题引用未知单元，请重试课程生成。')
        diagnostic['questions']=await self.validate_questions(diagnostic['questions'],allowed)
        # One clarification round at most, asked before the pretest.
        diagnostic['clarifications']=diagnostic['clarifications'][:1]
        c['diagnostic']=diagnostic;c['clarifications']=diagnostic['clarifications']
        c['current_unit_id']=order[0]
        c['mastery']={id:{'status':'unknown','score':None,'failures':0,'evidence':[]} for id in order}
        c['sources_verified']=bool(c['source_ids'])
        docs=[]
        if not c['source_ids']:
            docs.append(('reviews',self.review(c,'course','缺少可核查教学来源，课程草案待审核。',{'units':c['units']})))
        self.db.save_bundle(c,docs)
        return {'course_id':c['id']}

    async def clarify(self,id,answers,progress=None):
        c=self.db.get('courses',id)
        if c['status']!='diagnostic':raise ValueError('诊断已结束，请在学习对话中补充目标。')
        c['profile']['clarification']=answers
        d=await self.call(c,'diagnostic',{'learner':c['profile'],'known_units':c['units'],'sources':source_context(self.sources(c))},Diagnostic,progress)
        d['questions']=await self.validate_questions(d['questions'],set(u['id'] for u in c['units']))
        d['clarifications']=[]
        c['diagnostic']=d;c['clarifications']=d['clarifications'];self.db.put('courses',id,c)
        return {'course_id':id}

    async def validate_questions(self,questions,allowed,keep_all=False):
        """Independent answer checks. Generated items failing them are dropped;
        fixed sets (``keep_all``) keep every item so answer sheets still match."""
        from .mathcheck import verify_problem
        ids=set();result=[]
        for q in questions:
            if q['id'] in ids or q['unit_id'] not in allowed:raise ValueError('题目ID重复或超出教学范围。')
            ids.add(q['id'])
            if q['kind']=='expression':
                v=await asyncio.to_thread(verify_problem,q)
                if v['status']=='incorrect' and not keep_all:continue
                q['validation']=v
            else:q['validation']={'status':'undetermined','detail':'解释题由 AI 按量规审核，当前结论置信度有限。'}
            uncertain=rp.question_uncertain(q['validation'])
            rp.mark(q,uncertain,'AI 已完成独立答案核验。','AI 建议检查题意、条件和推导过程。',['答案核验不充分'] if uncertain else [])
            result.append(q)
        if not result:raise ValueError('生成题目未通过独立答案核验，请重新生成。')
        return result

    def review(self,c,kind,reason,content,uncertain=True,**extra):
        return rp.review_record(c['id'],kind,reason,content,record_id=uid(),created_at=now(),uncertain=uncertain,**extra)

    async def grade(self,c,questions,answers,progress=None,context=None):
        from .mathcheck import verify_answer
        answer_by={a['question_id']:a['answer'] for a in answers}
        qids={q['id'] for q in questions}
        if len(answer_by)!=len(answers) or set(answer_by)!=qids:raise ValueError('请逐题提交本次所有题目的答案，题目ID不能重复。')
        checks={}
        for q in questions:
            if q['kind']=='expression':
                checks[q['id']]=await asyncio.to_thread(verify_answer,answer_by[q['id']],str(q['expected_answer']),variables=q.get('variables',['x']),domain=q.get('domain','real'))
            else:checks[q['id']]={'status':'undetermined','detail':'过程/开放题需按量规审核。'}
        payload={'learner':c['profile'],'questions':questions,'answers':answers,'independent_checks':checks}
        if context:payload.update(context)
        model=await self.call(c,'grading',payload,Grade,progress)
        model_by={i['question_id']:i for i in model['items']}
        if set(model_by)!=qids or len(model['items'])!=len(qids):raise ValueError('批改结果题目不完整，请重试。')
        items=[]
        for q in questions:
            item=model_by[q['id']];check=checks[q['id']]
            trusted=q.get('validation',{}).get('status')=='verified'
            uncertain=rp.grade_item_uncertain(q,check,item['needs_human_review'])
            # A verified SymPy check outranks the model's score.
            if check['status']=='verified' and trusted:item['score']=1.0
            elif check['status']=='incorrect' and trusted:item['score']=0.0
            item.update(expected_answer=q['expected_answer'],solution=q['solution'],
                        answer=answer_by[q['id']],evidence={'mathematical_check':check,'rubric_review':item['evidence'],'reference_validation':q.get('validation',{})})
            rp.mark(item,uncertain,'AI 已结合独立核验与评分量规确认本题作答。','AI 建议重新检查推导、条件和题意。',
                    [item.get('error_type') or '需进一步核对'] if uncertain else [])
            items.append(item)
        uncertain=any(i['ai_uncertain'] for i in items)
        result={'score':sum(i['score'] for i in items)/len(items),'items':items,'explanation':model['explanation']}
        return rp.mark(result,uncertain,'AI 已完成自动审核并确认本次作答达到当前练习标准。','AI 已完成自动审核；标注不确定的题目请按建议补充或重做。',
                       [f'第 {n} 题建议核对' for n,i in enumerate(items,1) if i['ai_uncertain']])

    async def diagnose(self,id,data,progress=None):
        c=self.db.get('courses',id)
        if c['status']!='diagnostic':
            if c.get('diagnostic_result'):return {'course_id':id}
            raise ValueError('课程当前不处于前测阶段。')
        if c.get('clarifications'):raise ValueError('请先补充诊断澄清信息。')
        result=c.get('diagnostic_result')
        if result is None:
            result=await self.grade(c,c['diagnostic']['questions'],data['answers'],progress)
            c['diagnostic_result']=result
            c['profile']['diagnostic_evidence']=result
            c['profile']['unknown_units']=[u['id'] for u in c['units']]
            measured={}
            for q in c['diagnostic']['questions']:
                item=next(i for i in result['items'] if i['question_id']==q['id'])
                measured.setdefault(q['unit_id'],[]).append(item)
            c['diagnostic_mastery']={}
            # One brief pretest item is insufficient to declare an entire unit mastered.
            for unitid in validate_graph(c['units']):
                items=measured.get(unitid,[])
                prereqs=next(u for u in c['units'] if u['id']==unitid).get('prerequisites',[])
                if len(items)>=2 and all(i['score']>=MASTERY and not i.get('ai_uncertain') for i in items) and all(p in c['diagnostic_mastery'] for p in prereqs):
                    c['diagnostic_mastery'][unitid]={'status':'mastered','score':sum(i['score'] for i in items)/len(items),'failures':0,'evidence':['diagnostic:'+i['question_id'] for i in items]}
            # Practice done before the pretest keeps its evidence.
            self.recompute(c)
            docs=[]
            if result.get('ai_uncertain'):docs.append(('reviews',self.review(c,'diagnostic','前测由 AI 自动审核；部分答案置信度有限。',{'result':result,'questions':c['diagnostic']['questions']})))
            # The graded pretest survives a failed planning call; a retry only replans.
            self.db.save_bundle(c,docs)
        payload={'learner':c['profile'],'allowed_units':c['units'],'mastery':c['mastery'],
                 'instruction':'只规划与目标相关的单元及其所有先修。尚未测量的知识不可直接跳过。'}
        plan=await self.call(c,'planning',payload,Plan,progress)
        graph=validate_graph(c['units']);allowed=set(graph)
        if not plan['unit_order'] or len(set(plan['unit_order']))!=len(plan['unit_order']) or not set(plan['unit_order'])<=allowed:
            raise ValueError('课程计划包含未知或重复单元，请重试。')
        planned=set(plan['unit_order'])
        missing=with_prerequisites(c['units'],planned)
        planned|=missing
        plan['unit_order']=[x for x in graph if x in planned]
        if missing:plan['reason']+='；系统依据知识图补齐未测先修单元。'
        if any(s['unit_id'] not in planned for s in plan['sessions']):raise ValueError('教学节奏引用了计划以外的单元。')
        sessions={s['unit_id']:s for s in plan['sessions']}
        for unitid in plan['unit_order']:
            if unitid not in sessions:sessions[unitid]={'unit_id':unitid,'minutes':c['profile'].get('minutes_per_session',30),'focus':'先修知识补全与诊断确认'}
        plan['sessions']=[sessions[i] for i in plan['unit_order']]
        plan['goal']=plan['goal'].strip() or c['profile'].get('goal') or c['topic']
        c['plan']=plan;c['status']='active';c['current_unit_id']=self.next_unit(c) or plan['unit_order'][0]
        self.db.put('courses',id,c)
        return await self.lesson(id,{'mode':'continue'},progress)

    def next_unit(self,c):
        return progression.next_unit(c)

    def recompute(self,c):
        progression.recompute(c)

    async def lesson(self,id,data,progress=None):
        c=self.db.get('courses',id)
        remember_workspace(c)
        mode=data.get('mode','continue')
        target=data.get('unit_id') or (c['current_unit_id'] if mode in ('remedial','refresh') else self.next_unit(c))
        if not target:c['status']='completed';self.db.put('courses',id,c);return {'course_id':id,'action':'lesson'}
        by={u['id']:u for u in c['units']}
        if target not in by:raise ValueError('知识单元不存在。')
        cached=c.get('workspaces',{}).get(target,{})
        fresh=mode in ('remedial','refresh')
        if cached.get('lesson') and cached.get('assignment') and not fresh:
            c['current_unit_id']=target;c['lesson']=cached['lesson'];c['assignment']=cached.get('assignment')
            self.db.put('courses',id,c)
            return {'course_id':id,'unit_id':target,'action':'lesson','cached':True}
        valid_sources=set(c['source_ids'])
        if cached.get('lesson') and not fresh:
            # A lesson saved before a failed exercise step is reused; only the exercise is regenerated.
            lesson=cached['lesson']
        else:
            pending=[h for h in c['history'] if h['unit_id']==target and h['feedback'].get('ai_uncertain')]
            payload={'learner':c['profile'],'unit':by[target],'plan':c.get('plan'),'mode':mode,
                     'previous_feedback':c.get('last_feedback'),'sources':source_context(self.sources(c)),
                     'previous_lesson':cached.get('lesson'),'pending_review':bool(pending),
                     'prerequisite_evidence':[{'unit_id':p,'title':by[p]['title'],
                         **c.get('mastery',{}).get(p,{'status':'unknown'})} for p in by[target].get('prerequisites',[])],
                     'instruction':'自由学习模式：先修未掌握时补充必要背景，不据浏览推断掌握。'}
            lesson=await self.call(c,'teaching',payload,Lesson,progress)
            valid_citations=bool(lesson['citations']) and set(lesson['citations'])<=valid_sources
            lesson['citations']=[s for s in lesson['citations'] if s in valid_sources]
            rp.mark(lesson,not valid_citations,'AI 已检查引用关联与讲解结构；请结合例题验证关键推导。',
                    'AI 未找到完整有效引用，建议对关键结论进行独立核对。',[] if valid_citations else ['引用缺失或无效'])
            lesson['verification_note']='AI 已完成来源关联检查；关键推导建议自行核对。' if valid_citations else 'AI 检查发现引用缺失或无效，已给出风险提示。'
            # Safe plot data generated numerically here; no arbitrary expression evaluation in browser.
            plot=builtin_plot(target) if c.get('builtin') else None
            if plot:lesson['plot']=plot
            # Earlier units were stored by remember_workspace above; this unit now starts a new lesson.
            c['lesson']=lesson;c['assignment']=None;c['current_unit_id']=target
            c.setdefault('workspaces',{})[target]={'lesson':copy.deepcopy(lesson)}
            self.db.save_bundle(c,[('reviews',self.review(c,'lesson',lesson['verification_note'],{'lesson':lesson,'unit_id':target},
                                                          uncertain=lesson['ai_uncertain'],unit_id=target))])
        assignment_payload={'learner':c['profile'],'unit':by[target],'lesson':lesson,
            'previous_questions':[q['prompt'] for h in c['history'][-4:] for q in h.get('questions',[])],
            'sources':source_context(self.sources(c))}
        generated=await self.call(c,'assignment',assignment_payload,Assignment,progress)
        if c.get('builtin') and out_of_scope_assignment(generated['questions'],target):
            assignment_payload['scope_feedback']='上一版题目考查尚未进入的单元。只考当前单元目标；不得借用未来单元概念。'
            generated=await self.call(c,'assignment',assignment_payload,Assignment,progress)
        if c.get('builtin') and out_of_scope_assignment(generated['questions'],target):
            raise ValueError('生成练习超出当前单元教学范围，未向学生发布。请重试。')
        questions=await self.validate_questions(generated['questions'],{target})
        for q in questions:
            if not q['source_ids'] or not set(q['source_ids'])<=valid_sources:
                q['validation']={'status':'undetermined','detail':'题目缺少有效资料引用；AI 已标记风险并给出建议。'}
                rp.mark(q,True,'','题目缺少有效资料引用，建议结合讲义自行核对。',['引用缺失或无效'])
        c['lesson']=lesson;c['assignment']={'id':uid(),'unit_id':target,'questions':questions,'created_at':now(),'submitted':False}
        c['current_unit_id']=target
        if c['status']!='diagnostic':c['status']='active'
        docs=[]
        if any(q['ai_uncertain'] for q in questions):
            docs.append(('reviews',self.review(c,'assignment','题目或参考答案存在待核验项。',{'assignment':c['assignment']},unit_id=target)))
        remember_workspace(c)
        self.db.save_bundle(c,docs)
        return {'course_id':id,'unit_id':target,'action':'lesson'}

    async def submit(self,id,data,progress=None):
        c=self.db.get('courses',id)
        key=data['request_id']
        if key in c.get('processed',{}):return c['processed'][key]
        assignment=c.get('assignment')
        if not assignment or assignment['id']!=data['assignment_id']:
            assignment=next((w.get('assignment') for w in c.get('workspaces',{}).values()
                            if (w.get('assignment') or {}).get('id')==data['assignment_id']),None)
        if not assignment or assignment['id']!=data['assignment_id']:raise ValueError('作业已更新，请刷新后提交当前作业。')
        # Legacy records may contain a teacher-block flag; it must not prevent the learner continuing.
        assignment['blocked']=False
        if assignment.get('submitted'):raise ValueError('本次作业已提交，请查看反馈或生成补救练习。')
        result=await self.grade(c,assignment['questions'],data['answers'],progress)
        history={'id':uid(),'assignment_id':assignment['id'],'unit_id':assignment['unit_id'],'feedback':result,
                 'questions':copy.deepcopy(assignment['questions']),'answers':data['answers'],'created_at':now(),'rubric_version':assignment.get('rubric_version',1)}
        c['history'].append(history);assignment['submitted']=True
        docs=[]
        if result.get('ai_uncertain'):
            docs.append(('reviews',self.review(c,'grade','开放题、答案核验或评分存在不确定项；AI 已给出改进建议。',copy.deepcopy(history),
                                                history_id=history['id'],unit_id=assignment['unit_id'])))
        for item in result['items']:
            if item['score']<MASTERY:
                q=next(q for q in assignment['questions'] if q['id']==item['question_id'])
                due=due_after(0)
                docs.append(('notebook',{'id':uid(),'course_id':id,'unit_id':assignment['unit_id'],'question':q['prompt'],'private_question':q,
                    'answer':item['answer'],'feedback':item['feedback'],'next_due':due,'stage':0,'created_at':now()}))
        self.recompute(c)
        result=self.labelled(c['last_feedback'],id,assignment['unit_id'],'answers')
        c.setdefault('processed',{})[key]=copy.deepcopy(result)
        if (c.get('assignment') or {}).get('id')==assignment['id']:remember_workspace(c)
        self.db.save_bundle(c,docs)
        if result['decision']=='remedial' and c['mastery'][assignment['unit_id']]['failures']>=2:
            try:
                revised=await self.call(c,'planning',{'learner':c['profile'],'allowed_units':c['units'],'mastery':c['mastery'],
                    'previous_plan':c.get('plan'),'recent_failures':c['history'][-2:],'instruction':'学生连续未达标。必须针对错误重新安排补讲方式与练习重点，不提前推进新单元。'},Plan,progress)
                allowed=set((c.get('plan') or {}).get('unit_order') or validate_graph(c['units']))
                if any(s['unit_id'] not in allowed for s in revised['sessions']):raise ValueError('补救计划包含课程外单元。')
                c.setdefault('plan_revisions',[]).append({'at':now(),'previous':copy.deepcopy(c.get('plan')),'reason':revised['reason']})
                c.setdefault('plan',{'unit_order':list(allowed)})
                c['plan']['sessions']=revised['sessions'];c['plan']['reason']=revised['reason']
                c['last_feedback']['explanation']+=' 补救计划：'+revised['reason']
                result=self.labelled(c['last_feedback'],id,assignment['unit_id'],'answers')
                c['processed'][key]=copy.deepcopy(result)
                self.db.put('courses',id,c)
            except (ValueError,RuntimeError):
                result['replan_notice']='评分已保存；补救计划生成暂未完成，可点击补讲继续。'
        return result

    @staticmethod
    def labelled(result,course_id,unit_id,action):
        """Task results name their course and unit so the page refreshes the right view."""
        return {**copy.deepcopy(result),'course_id':course_id,'unit_id':unit_id,'action':action}

    def resolve(self,id,data,reviewer=None):
        """Teacher review channel. AI review stays the default; an administrator may
        confirm the AI result or correct one question's score, which recomputes progress."""
        r=self.db.get('reviews',id)
        if r.get('resolution_request_id')==data['request_id']:return {'ok':True,'teacher_status':r.get('teacher_status')}
        c=self.db.get('courses',r['course_id'])
        action=data['action'];score=data.get('score')
        decision={'action':action,'reason':data['reason'],'by':reviewer,'at':now()}
        docs=[]
        if action=='revise':
            if score is None:raise ValueError('改分时请填写 0–1 之间的分数。')
            h=next((h for h in c['history'] if h['id']==r.get('history_id')),None)
            if h is None:raise ValueError('只有练习评分记录可以改分。')
            items=h['feedback']['items']
            qid=data.get('question_id') or r.get('question_id') or (items[0]['question_id'] if len(items)==1 else None)
            item=next((i for i in items if i['question_id']==qid),None)
            if item is None:raise ValueError('请选择要改分的题目。')
            item.setdefault('original_score',item['score'])
            item.update(score=float(score),teacher_score=float(score),ai_uncertain=False,teacher_review=decision)
            h['feedback']['score']=sum(i['score'] for i in items)/len(items)
            h['feedback']['ai_uncertain']=any(i.get('ai_uncertain') for i in items)
            decision['question_id']=qid
            self.recompute(c)
        elif action=='approve' and r.get('history_id'):
            h=next((h for h in c['history'] if h['id']==r['history_id']),None)
            if h:
                for i in h['feedback']['items']:
                    if not r.get('question_id') or i['question_id']==r['question_id']:i['teacher_review']=decision
        r.update(teacher_status='resolved',teacher_review=decision,resolution_request_id=data['request_id'],resolved_at=now())
        if r.get('status')=='pending':r['status']='ai_reviewed'
        docs.append(('reviews',r))
        self.db.save_bundle(c,docs)
        return {'ok':True,'teacher_status':'resolved','course_id':c['id']}

    async def chat(self,id,data,progress=None):
        c=self.db.get('courses',id)
        unit_id=data.get('unit_id') or c.get('current_unit_id')
        workspace=self.workspace(id,unit_id)
        if data.get('request_id') in c.get('chat_requests',{}):return c['chat_requests'][data['request_id']]
        learner={k:v for k,v in c['profile'].items() if k!='diagnostic_evidence'}
        feedback=[{'unit_id':h['unit_id'],'score':h['feedback']['score'],'ai_uncertain':h['feedback'].get('ai_uncertain',False),
            'items':[{k:item.get(k) for k in ('question_id','score','feedback','error_type','answer')}
                     for item in h['feedback']['items']]} for h in c.get('history',[])[-6:]]
        # Answer keys deliberately absent. LLM can infer solutions; prompt asks for graded hints.
        result=await self.call(c,'chat',{'learner':learner,'lesson':workspace['lesson'],'message':data['message'],
            'unit':workspace['unit'],'mastery':c.get('mastery',{}),'recent_feedback':feedback,
            'selection':{'text':data.get('selected_text','')[:2000],'context':data.get('surrounding_text','')[:4000]},
            'prerequisite_evidence':workspace['prerequisites'],
            'hint_level':data.get('hint_level',1),'recent_messages':workspace['messages'][-8:],
            'assignment':(workspace.get('assignment') or {}).get('questions',[]),
            'sources':source_context(self.sources(c))},Reply,progress)
        cited=bool(result['citations']) and set(result['citations'])<=set(c['source_ids'])
        rp.mark(result,not cited or result['needs_human_review'],'AI 已结合讲义与资料回答。',
                '回答引用不足，建议结合讲义与原文核对关键结论。',[] if cited else ['引用缺失或无效'])
        result['citations']=[s for s in result['citations'] if s in c['source_ids']]
        c.setdefault('messages',[]).extend([{'role':'user','content':data['message'],'unit_id':unit_id,'selected_text':data.get('selected_text','')},
            {'role':'assistant','content':result['reply'],'unit_id':unit_id,'citations':result['citations'],
             'needs_human_review':False,'ai_uncertain':result['ai_uncertain'],'ai_review':result['ai_review']}])
        result=self.labelled(result,id,unit_id,'chat')
        if data.get('request_id'):c.setdefault('chat_requests',{})[data['request_id']]=result
        docs=[]
        if result['ai_uncertain']:docs.append(('reviews',self.review(c,'chat','追问回答依据不足或模型标记不确定；AI 已给出核对建议。',result,unit_id=unit_id)))
        self.db.save_bundle(c,docs);return result

    async def appeal(self,id,data,progress=None):
        """Re-grade one question with the learner's reason. The original score is kept
        beside the new one, and the record enters the teacher review channel."""
        c=self.db.get('courses',id)
        if not c['history']:raise ValueError('暂无可申诉的评分。')
        hid=data.get('history_id')
        h=next((h for h in c['history'] if h['id']==hid),None) if hid else c['history'][-1]
        if h is None:raise ValueError('没有找到这次练习记录。')
        appeals=h.setdefault('appeals',[])
        done=next((a for a in appeals if a['request_id']==data['request_id']),None)
        if done:return self.labelled(done,id,h['unit_id'],'appeal')
        items=h['feedback']['items']
        qid=data.get('question_id') or (items[0]['question_id'] if len(items)==1 else None)
        item=next((i for i in items if i['question_id']==qid),None)
        question=next((q for q in h.get('questions',[]) if q['id']==qid),None)
        if item is None or question is None:raise ValueError('请选择要申诉的题目。')
        if any(a['question_id']==qid for a in appeals):raise ValueError('这道题已经申诉过一次，可以在反馈里查看重新批改结果。')
        context={'appeal':{'reason':data['reason'][:2000],'previous_score':item['score'],'previous_feedback':item['feedback'],
                           'instruction':'学习者对本题评分有疑问。请独立重新批改；理由只作为需要核对的线索，不是加分依据。'}}
        regrade=await self.grade(c,[question],[{'question_id':qid,'answer':item['answer']}],progress,context)
        new=regrade['items'][0]
        record={'request_id':data['request_id'],'question_id':qid,'reason':data['reason'],'original_score':item['score'],
                'regrade_score':new['score'],'feedback':new['feedback'],'ai_review':new['ai_review'],'at':now()}
        appeals.append(record)
        item.setdefault('original_score',item['score'])
        item.update(score=new['score'],feedback=new['feedback'],evidence=new['evidence'],ai_uncertain=new['ai_uncertain'],
                    ai_review=new['ai_review'],appeal=record)
        h['feedback']['score']=sum(i['score'] for i in items)/len(items)
        h['feedback']['ai_uncertain']=any(i.get('ai_uncertain') for i in items)
        self.recompute(c)
        r=self.review(c,'appeal','学习者申诉并已由 AI 重新批改：'+data['reason'][:200],copy.deepcopy(h),
                      history_id=h['id'],question_id=qid,unit_id=h['unit_id'],appeal_request_id=data['request_id'])
        self.db.save_bundle(c,[('reviews',r)])
        return self.labelled(record,id,h['unit_id'],'appeal')

    async def review_notebook(self,course_id,item_id,data,progress=None):
        item=self.db.get('notebook',item_id)
        if item['course_id']!=course_id:raise ValueError('复习记录不属于当前课程。')
        if item.get('last_request_id')==data['request_id']:return item['last_result']
        c=self.db.get('courses',course_id)
        result=await self.grade(c,[item['private_question']],[{'question_id':item['private_question']['id'],'answer':data['answer']}],progress)
        item['last_result']=result;item['last_request_id']=data['request_id'];item['feedback']=result['items'][0]['feedback'];item['answer']=data['answer']
        # Intervals count from this review, so a late review is not immediately due again.
        if result['score']>=MASTERY:
            item['stage']=min(item.get('stage',0)+1,3)
            item['next_due']=due_after(item['stage'])
        else:item['next_due']=due_after(0)
        item.pop('due_dates',None)
        docs=[('notebook',item)]
        if result.get('ai_uncertain'):
            docs.append(('reviews',self.review(c,'notebook','复习答案由 AI 自动审核；置信度有限，已给出建议。',{'item':item,'result':result},item_id=item_id)))
        self.db.save_bundle(c,docs)
        return result

    def assessment_questions(self,c,kind):
        if kind not in ('pre','post','delayed'):raise ValueError('未知测验类型。')
        bank=c.get('question_bank',[])
        if not bank:raise ValueError('该主题尚无独立评测题库；请先生成或添加评测资料。')
        index=('pre','post','delayed').index(kind)
        return [q for n,q in enumerate(bank) if n%3==index][:12]

    def assessment(self,id,kind):
        # Pure derivation: GET never writes a stale course snapshot over a concurrent answer.
        c=self.db.get('courses',id)
        return {'questions':[public_question(q) for q in self.assessment_questions(c,kind)],'kind':kind}

    async def submit_assessment(self,id,data,progress=None):
        c=self.db.get('courses',id)
        questions=copy.deepcopy(self.assessment_questions(c,data['kind']))
        # The learner answered exactly this form, so no item may be dropped here.
        questions=await self.validate_questions(questions,set(u['id'] for u in c['units']),keep_all=True)
        result=await self.grade(c,questions,data['answers'],progress)
        record={'id':uid(),'kind':data['kind'],'at':now(),'result':result,'participant_type':'human_unverified'}
        c.setdefault('assessments',[]).append(record)
        docs=[]
        if result.get('ai_uncertain'):
            docs.append(('reviews',self.review(c,'assessment','测验评分由 AI 自动审核；部分答案置信度有限。',{'assessment':record},assessment_id=record['id'])))
        self.db.save_bundle(c,docs);return self.labelled(result,id,None,'assessment')


# One numeric illustration per built-in calculus unit; the browser never evaluates expressions.
PLOTS={
    'u01':('√x',lambda x:math.sqrt(x),0,4,'函数 y=√x：定义域是 x≥0。'),
    'u02':('sin x / x',lambda x:math.sin(x)/x if x else None,-10,10,'x→0 时 sin x / x 趋近 1，但在 x=0 处没有定义。'),
    'u03':('x³−x−1',lambda x:x**3-x-1,-2,2,'连续函数在 [1,2] 两端异号，介值定理保证中间有零点。'),
    'u04':('x²',lambda x:x*x,-3,3,'函数 y=x²：曲线越陡，导数的绝对值越大。'),
    'u05':('sin(x²)',lambda x:math.sin(x*x),-3,3,'复合函数 sin(x²)：链式法则给出导数 2x·cos(x²)。'),
    'u06':('√(4−x²)',lambda x:math.sqrt(max(0.0,4-x*x)),-2,2,'圆 x²+y²=4 的上半部分：隐函数求导得 dy/dx=−x/y。'),
    'u07':('x³−3x',lambda x:x**3-3*x,-2.5,2.5,'x³−3x 在 x=±1 处导数为 0，分别是局部极大和极小。'),
    'u08':('x²/2',lambda x:x*x/2,-3,3,'x²/2 是 x 的一个原函数；加任意常数仍是原函数。'),
    'u09':('x²',lambda x:x*x,0,2,'∫₀² x² dx = 8/3，是曲线下方的面积。'),
    'u10':('x·eˣ',lambda x:x*math.exp(x),-4,1,'x·eˣ 的积分适合用分部积分。'),
    'u11':('1/x²',lambda x:1/(x*x),0.5,6,'∫₁^∞ 1/x² dx 收敛到 1：曲线衰减足够快。'),
    'u12':('eˣ',lambda x:math.exp(x),-2,2,'eˣ 在 0 附近可用 1+x+x²/2 近似。'),
}

def builtin_plot(unit_id):
    spec=PLOTS.get(unit_id)
    if not spec:return None
    label,f,lo,hi,caption=spec
    points=[]
    for i in range(201):
        x=lo+(hi-lo)*i/200
        try:y=f(x)
        except (ValueError,ZeroDivisionError,OverflowError):y=None
        points.append({'x':round(x,4),'y':None if y is None else round(y,6)})
    return {'expression':label,'x_min':lo,'x_max':hi,'points':points,'caption':caption}
