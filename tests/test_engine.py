import pytest
from learning.db import Store
from learning.engine import Engine, out_of_scope_assignment, public_course, validate_graph
from learning.schemas import Question

def course():
    return {'id':'c','topic':'极限','title':'极限','status':'active','current_unit_id':'u1',
      'units':[{'id':'u1','title':'起点','prerequisites':[]},{'id':'u2','title':'下一节','prerequisites':['u1']}],
      'mastery':{},'history':[],'trace':[], 'profile':{},'source_ids':[], 'review_items':[],
      'assignment':{'id':'a','unit_id':'u1','questions':[{'id':'q','prompt':'计算1+1','unit_id':'u1','kind':'expression','expected_answer':'2','solution':'加法','rubric':[{'criterion':'正确结果','points':1}],'verification':{'type':'value','expression':'1+1','expected':'2'},'validation':{'status':'verified'}}]},
      'plan':{'unit_order':['u1','u2']},'diagnostic':{'questions':[]}}

class Fake:
    async def call(self, role,payload,schema):
        if role=='grading':
            return schema.model_validate({'items':[{'question_id':q['id'],'score':1,'feedback':'检查计算。','evidence':'量规比对','error_type':'calculation','needs_human_review':False} for q in payload['questions']],'explanation':'基于本次作答。'}),{'provider':'TEST_ONLY','model':'fixture','usage':{}}
        if role=='planning':
            return schema.model_validate({'unit_order':['u1','u2'],'sessions':[{'unit_id':'u1','minutes':15,'focus':'用数轴重新理解加法'}],'weekly_hours':2,'goal':'补救','reason':'根据两次加法错误更换例子并降低练习复杂度。'}),{'provider':'TEST_ONLY','model':'fixture','usage':{}}
        raise AssertionError(role)

def test_public_course_never_leaks_current_answer_through_trace():
    c=course();c['trace']=[{'agent':'assignment','input':{},'output':{'questions':c['assignment']['questions']}}]
    p=public_course(c)
    assert 'expected_answer' not in str(p)
    assert 'solution' not in str(p['assignment'])
    assert 'output' not in p['trace'][0]

def test_cycle_and_unknown_dependency_rejected():
    with pytest.raises(ValueError):validate_graph([{'id':'a','prerequisites':['b']},{'id':'b','prerequisites':['a']}])
    with pytest.raises(ValueError):validate_graph([{'id':'a','prerequisites':['missing']}])


def test_builtin_assignment_scope_checks_prompt_not_just_unit_id():
    questions=[{'id':'q1','unit_id':'u01','prompt':'计算 lim(x→1) (x²-1)/(x-1)'},
               {'id':'q2','unit_id':'u01','prompt':'求函数 sqrt(x-1) 的定义域'}]
    assert out_of_scope_assignment(questions,'u01')==['q1']
    assert out_of_scope_assignment(questions[1:],'u01')==[]
    assert out_of_scope_assignment([{'id':'q3','prompt':'求函数的导数'}],'u02')==['q3']


@pytest.mark.asyncio
async def test_out_of_scope_assignment_is_retried_then_blocked(tmp_path):
    class ScopeFake:
        def __init__(self):self.assignment_calls=0
        async def call(self,role,payload,schema):
            if role=='teaching':
                raw={'title':'函数定义域','body':'定义域说明','examples':[{'question':'求定义域','solution':'检查分母'}],
                     'misconceptions':[],'citations':[]}
            elif role=='assignment':
                self.assignment_calls+=1
                raw={'questions':[{'id':'q','unit_id':'u01','kind':'open',
                    'prompt':'计算极限 lim(x→1) x', 'expected_answer':'1','solution':'趋近1',
                    'rubric':[{'criterion':'结果','points':1}], 'source_ids':[]}]}
            else:raise AssertionError(role)
            return schema.model_validate(raw),{'provider':'TEST_ONLY','model':'fixture','usage':{}}
    db=Store(tmp_path/'scope.sqlite');c=course()
    c['builtin']=True;c['current_unit_id']='u01';c['units']=[{'id':'u01','title':'函数与定义域','prerequisites':[]}]
    c['plan']={'unit_order':['u01']};c['assignment']=None
    db.put('courses','c',c);fake=ScopeFake();e=Engine(db,fake)
    with pytest.raises(ValueError,match='超出当前单元'):
        await e.lesson('c',{'mode':'continue'})
    assert fake.assignment_calls==2
    assert db.get('courses','c')['assignment'] is None

@pytest.mark.asyncio
async def test_correct_answer_advances_actual_unit_and_is_idempotent(tmp_path):
    db=Store(tmp_path/'db');db.put('courses','c',course());e=Engine(db,Fake())
    result=await e.submit('c',{'assignment_id':'a','answers':[{'question_id':'q','answer':'4/2'}],'request_id':'r'})
    assert result['decision']=='advance' and result['next_unit_id']=='u2'
    assert db.get('courses','c')['mastery']['u1']['status']=='mastered'
    await e.submit('c',{'assignment_id':'a','answers':[{'question_id':'q','answer':'0'}],'request_id':'r'})
    assert len(db.get('courses','c')['history'])==1

@pytest.mark.asyncio
async def test_two_failures_do_not_advance_despite_model_saying_full_score(tmp_path):
    db=Store(tmp_path/'db');c=course();db.put('courses','c',c);e=Engine(db,Fake())
    for n in range(2):
        c=db.get('courses','c');c['assignment']['id']='a'+str(n);c['assignment']['submitted']=False;db.put('courses','c',c)
        r=await e.submit('c',{'assignment_id':'a'+str(n),'answers':[{'question_id':'q','answer':'7'}],'request_id':str(n)})
    assert r['decision']=='remedial' and r['next_unit_id']=='u1'
    assert '补讲' in r['explanation']
    assert db.get('courses','c')['mastery']['u1']['failures']==2
    assert db.get('courses','c')['plan_revisions']
    assert '数轴' in db.get('courses','c')['plan']['sessions'][0]['focus']

@pytest.mark.asyncio
async def test_open_grade_is_ai_reviewed_and_progresses_without_teacher_gate(tmp_path):
    db=Store(tmp_path/'db');c=course();c['assignment']['questions'][0]['kind']='open';db.put('courses','c',c);e=Engine(db,Fake())
    r=await e.submit('c',{'assignment_id':'a','answers':[{'question_id':'q','answer':'自己的解释'}],'request_id':'r'})
    assert r['decision']=='advance'
    review=db.list('reviews')[0]
    assert review['status']=='ai_reviewed' and review['review_mode']=='ai'
    c=db.get('courses','c')
    assert c['mastery']['u1']['status']=='mastered' and c['last_feedback']['decision']=='advance'

@pytest.mark.asyncio
async def test_unknown_question_and_stale_assignment_rejected(tmp_path):
    db=Store(tmp_path/'db');db.put('courses','c',course());e=Engine(db,Fake())
    with pytest.raises(ValueError):await e.submit('c',{'assignment_id':'old','answers':[],'request_id':'r'})
    with pytest.raises(ValueError):await e.submit('c',{'assignment_id':'a','answers':[{'question_id':'foreign','answer':'2'}],'request_id':'r'})


@pytest.mark.asyncio
async def test_unknown_unit_is_rejected_before_generation(tmp_path):
    db=Store(tmp_path/'db');c=course();c['units'][1]['prerequisites']=[]
    db.put('courses','c',c);e=Engine(db,Fake())
    with pytest.raises(ValueError,match='不存在'):
        await e.lesson('c',{'mode':'continue','unit_id':'missing'})

@pytest.mark.asyncio
async def test_appeal_records_ai_recheck_without_pending_queue(tmp_path):
    db=Store(tmp_path/'db');c=course();c['assignment']['questions'][0]['kind']='open';db.put('courses','c',c);e=Engine(db,Fake())
    await e.submit('c',{'assignment_id':'a','answers':[{'question_id':'q','answer':'解释'}],'request_id':'r'})
    result=await e.appeal('c',{'question_id':'q','reason':'不同解法希望重评','request_id':'appeal'})
    assert result['original_score']==1 and result['regrade_score']==1 and result['course_id']=='c'
    appeal=next(r for r in db.list('reviews') if r['kind']=='appeal')
    assert appeal['status']=='ai_reviewed' and appeal['teacher_status']=='open' and appeal['question_id']=='q'
    assert '不同解法' in appeal['reason']
    assert len([r for r in db.list('reviews') if r['status']=='pending'])==0
    item=db.get('courses','c')['history'][0]['feedback']['items'][0]
    assert item['original_score']==1 and item['appeal']['reason']=='不同解法希望重评'
    # Same request is idempotent; a second appeal on the same question is refused.
    assert (await e.appeal('c',{'question_id':'q','reason':'x','request_id':'appeal'}))['regrade_score']==1
    with pytest.raises(ValueError,match='申诉过'):await e.appeal('c',{'question_id':'q','reason':'x','request_id':'again'})

def test_assessment_get_is_read_only(tmp_path):
    db=Store(tmp_path/'db');c=course();c['question_bank']=c['assignment']['questions'];db.put('courses','c',c);e=Engine(db,Fake())
    before=db.get('courses','c')
    assert e.assessment('c','pre')['questions']
    assert db.get('courses','c')==before


@pytest.mark.asyncio
async def test_clarification_is_one_round_then_pretest_is_available(tmp_path):
    class DiagnosticFake:
        async def call(self,role,payload,schema):
            assert role=='diagnostic'
            return schema.model_validate({'summary':'根据补充信息安排前测',
                'clarifications':['再问函数知识','再问极限知识'],
                'questions':[{'id':'dq','prompt':'说明函数是什么','kind':'open','unit_id':'u1',
                              'rubric':[{'criterion':'概念清楚','points':1}],
                              'expected_answer':'对应关系','solution':'说明对应关系'}]}),{'provider':'TEST_ONLY','model':'fixture','usage':{}}
    db=Store(tmp_path/'db');c=course();c['status']='diagnostic';c['clarifications']=['请补充基础']
    db.put('courses','c',c)
    e=Engine(db,DiagnosticFake())
    await e.clarify('c','已经会画函数图像')
    updated=db.get('courses','c')
    assert updated['clarifications']==[]
    assert updated['diagnostic']['questions'][0]['id']=='dq'

@pytest.mark.asyncio
async def test_uncertain_notebook_has_resolvable_review(tmp_path):
    db=Store(tmp_path/'db');c=course();q=c['assignment']['questions'][0];q['kind']='open';db.put('courses','c',c)
    db.put('notebook','n',{'id':'n','course_id':'c','private_question':q,'stage':0,'due_dates':['d1','d3','d7'],'answer':'old'})
    e=Engine(db,Fake());await e.review_notebook('c','n',{'answer':'new','request_id':'r'})
    review=db.list('reviews')[0]
    assert review['kind']=='notebook'
    e.resolve(review['id'],{'action':'approve','reason':'模拟审核','request_id':'rr'})
    assert db.get('notebook','n')['stage']==1
