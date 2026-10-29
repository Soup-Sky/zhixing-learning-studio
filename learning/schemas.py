from typing import Literal,Any
from pydantic import BaseModel,Field,ConfigDict

class Model(BaseModel):
    model_config=ConfigDict(extra='ignore')

class Rubric(Model):
    criterion:str
    points:float=Field(ge=0,le=100)

class Question(Model):
    id:str
    prompt:str
    kind:Literal['expression','open']='open'
    unit_id:str
    difficulty:Literal['基础','应用','解释']='基础'
    rubric:list[Rubric]=Field(min_length=1)
    expected_answer:str
    solution:str
    hints:list[str]=Field(default_factory=list)
    variables:list[str]=Field(default_factory=lambda:['x'])
    domain:str='real'
    verification:dict[str,Any]=Field(default_factory=dict)
    source_ids:list[str]=Field(default_factory=list)

class Unit(Model):
    id:str
    title:str
    prerequisites:list[str]=Field(default_factory=list)
    objectives:list[str]=Field(default_factory=list)
    source_ids:list[str]=Field(default_factory=list)
    estimated_minutes:int=Field(default=30,ge=5,le=480)
    content:str=''
    review_status:str='ai_reviewed'

class Diagnostic(Model):
    summary:str
    clarifications:list[str]=Field(default_factory=list)
    strengths:list[str]=Field(default_factory=list)
    unknowns:list[str]=Field(default_factory=list)
    units:list[Unit]=Field(default_factory=list)
    questions:list[Question]=Field(min_length=1,max_length=6)

class SessionPlan(Model):
    unit_id:str
    minutes:int=Field(ge=5,le=480)
    focus:str

class Plan(Model):
    unit_order:list[str]
    reason:str
    weekly_hours:float=Field(gt=0,le=100)
    sessions:list[SessionPlan]
    # The learner already stated a goal; DeepSeek often omits restating it, so the engine fills it in.
    goal:str=''

class Example(Model):
    question:str
    solution:str

class Lesson(Model):
    title:str
    body:str
    examples:list[Example]=Field(min_length=1)
    misconceptions:list[str]
    citations:list[str]
    needs_human_review:bool=False

class Assignment(Model):
    questions:list[Question]=Field(min_length=1,max_length=4)

class GradeItem(Model):
    question_id:str
    score:float=Field(ge=0,le=1)
    feedback:str
    evidence:str
    error_type:str
    needs_human_review:bool
    rubric_scores:list[Rubric]=Field(default_factory=list)

class Grade(Model):
    items:list[GradeItem]
    explanation:str

class Reply(Model):
    reply:str
    citations:list[str]=Field(default_factory=list)
    needs_human_review:bool=False

class CourseInput(Model):
    topic:str=Field(min_length=1,max_length=200)
    background:str=Field(default='',max_length=2000)
    goal:str=Field(min_length=1,max_length=2000)
    hours_per_week:float=Field(default=3,gt=0,le=100)
    minutes_per_session:int=Field(default=30,ge=5,le=240)
    preference:str=Field(default='概念与例题结合',max_length=1000)
    search_web:bool=True
    source_ids:list[str]=Field(default_factory=list,max_length=20)
    request_id:str=Field(default='',max_length=100)

class Answer(Model):
    question_id:str
    answer:str=Field(max_length=8000)

class Submission(Model):
    answers:list[Answer]=Field(max_length=50)
    request_id:str=Field(min_length=1,max_length=100)
    assignment_id:str=''

class LessonRequest(Model):
    request_id:str=Field(min_length=1,max_length=100)
    mode:Literal['continue','remedial','refresh','review']='continue'
    unit_id:str|None=None

class ChatRequest(Model):
    message:str=Field(min_length=1,max_length=6000)
    hint_level:int=Field(default=1,ge=1,le=3)
    request_id:str=Field(min_length=1,max_length=100)
    unit_id:str|None=None
    selected_text:str=Field(default='',max_length=2000)
    surrounding_text:str=Field(default='',max_length=4000)

class ReviewRequest(Model):
    action:Literal['approve','reject','revise']
    reason:str=Field(min_length=1,max_length=4000)
    score:float|None=Field(default=None,ge=0,le=1)
    content:dict|None=None
    question_id:str|None=Field(default=None,max_length=100)
    request_id:str=Field(min_length=1,max_length=100)
