import {useState} from 'react';
import {ArrowRight,LoaderCircle} from 'lucide-react';
import type {Question} from './api';
import Markdown from './Markdown';
import SymbolInput from './SymbolInput';

export default function Questions({questions,submit,busy,label='提交答案',draftKey='',topic=''}:{questions:Question[];submit:(answers:{question_id:string;answer:string}[])=>void;busy:boolean;label?:string;draftKey?:string;topic?:string}){
 const key='zhixing-draft-'+draftKey;
 const [answers,setAnswers]=useState<Record<string,string>>(()=>{try{return draftKey?JSON.parse(localStorage.getItem(key)||'{}'):{};}catch{return {};}});
 const change=(id:string,value:string)=>{const next={...answers,[id]:value};setAnswers(next);if(draftKey)localStorage.setItem(key,JSON.stringify(next));};
 return <form onSubmit={e=>{e.preventDefault();submit(questions.map(q=>({question_id:q.id,answer:answers[q.id]||''})));}}>
  <div className="question-stack">{questions.map((q,i)=><section className="card question" key={q.id}>
   <div className="question-head"><span className="number">{String(i+1).padStart(2,'0')}</span><span className="badge">{q.kind==='expression'?'数学表达式':'开放回答'}</span></div>
   <Markdown text={q.prompt}/><label className="answer-label" htmlFor={'answer-'+q.id}>你的思考与答案</label>
   <SymbolInput topic={topic} id={'answer-'+q.id} required disabled={busy} value={answers[q.id]||''} onChange={value=>change(q.id,value)} rows={4} placeholder="写下推导过程或答案"/>
   {!!q.rubric?.length&&<details><summary>评分依据</summary>{q.rubric.map((r,j)=><p key={j}>{r.criterion} · {r.points} 分</p>)}</details>}
  </section>)}</div><button className="primary" disabled={busy||!questions.length}>{busy?<LoaderCircle className="spin" size={17}/>:<ArrowRight size={17}/>} {label}</button>
 </form>;
}
