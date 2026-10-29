import {useEffect,useRef,useState} from 'react';
import {MessageCircle,Send,X} from 'lucide-react';
import type {Course,Workspace} from './api';
import {api} from './api';
import Markdown from './Markdown';
import SymbolInput from './SymbolInput';
import {ReviewAdvice} from './LearningWorkspace';
type Passage={unit_id:string;text:string;context:string;x:number;y:number};
export default function SelectionAssistant({course,working,action,onError}:{course:Course;working:boolean;action:(path:string,body:object)=>void;onError:(text:string)=>void}){
 const [passage,setPassage]=useState<Passage>(),[context,setContext]=useState<Passage>(),[messages,setMessages]=useState<Workspace['messages']>([]),[message,setMessage]=useState(''),[level,setLevel]=useState(2),[pending,setPending]=useState(false);
 const log=useRef<HTMLDivElement>(null),count=useRef(0),sent=useRef<string|null>(null);
 const draftKey=(unit:string)=>'zhixing-chat-draft-'+course.id+'-'+unit;
 const open=(p:Passage)=>{setContext(p);setPassage(undefined);setMessage(localStorage.getItem(draftKey(p.unit_id))||'');};
 useEffect(()=>{const capture=()=>{const s=window.getSelection();if(!s||s.isCollapsed||!s.rangeCount){setPassage(undefined);return;}const range=s.getRangeAt(0),node=range.commonAncestorContainer;const element=node.nodeType===1?node as Element:node.parentElement;const surface=element?.closest<HTMLElement>('[data-learning-surface]');if(!surface||element?.closest('textarea,input,button,.assistant-drawer')){setPassage(undefined);return;}const end=s.focusNode?.nodeType===1?s.focusNode as Element:s.focusNode?.parentElement;if(end?.closest('[data-learning-surface]')!==surface)return;const rect=range.getBoundingClientRect(),text=s.toString().trim().slice(0,2000);if(text)setPassage({unit_id:surface.dataset.unitId||course.current_unit_id||course.units[0]?.id||'',text,context:(element?.textContent||surface.textContent||'').slice(0,4000),x:Math.max(8,Math.min(rect.left,innerWidth-150)),y:Math.max(8,Math.min(rect.bottom+8,innerHeight-60))});};
 const ask=(e:Event)=>{const id=(e as CustomEvent).detail.unit_id;open({unit_id:id,text:'',context:'',x:0,y:0});};
 document.addEventListener('selectionchange',capture);window.addEventListener('zhixing-ask',ask);window.addEventListener('scroll',capture,true);return()=>{document.removeEventListener('selectionchange',capture);window.removeEventListener('zhixing-ask',ask);window.removeEventListener('scroll',capture,true);};},[course.id]);
 useEffect(()=>{if(!context)return;let active=true;api<Workspace>(`/courses/${course.id}/units/${context.unit_id}`).then(ws=>{if(active){setMessages(ws.messages||[]);if(ws.messages.length>count.current){setPending(false);
  // The draft is cleared only once the answer arrived, so a failed request keeps the text.
  if(sent.current===context.unit_id){setMessage('');localStorage.removeItem(draftKey(context.unit_id));sent.current=null;}}count.current=ws.messages.length;}}).catch(e=>onError(e.message));return()=>{active=false;};},[context?.unit_id,course]);
 useEffect(()=>{if(!working)setPending(false);},[working]);
 useEffect(()=>{count.current=0;},[context?.unit_id]);
 useEffect(()=>{log.current?.scrollTo({top:log.current.scrollHeight,behavior:'smooth'});},[messages]);
 return <>{passage&&!context&&<button className="selection-ask primary small" style={{left:passage.x,top:passage.y}} onMouseDown={e=>e.preventDefault()} onClick={()=>open(passage)}><MessageCircle size={16}/> 划词提问</button>}
 {context&&<div className="assistant-backdrop" onClick={()=>setContext(undefined)}><aside className="assistant-drawer" role="dialog" aria-label="AI 学习助手" aria-modal="true" onClick={e=>e.stopPropagation()}><div className="section-title"><div><h3>AI 学习助手</h3><span className="small muted">{course.units.find(u=>u.id===context.unit_id)?.title}</span></div><button className="icon-button" aria-label="关闭学习助手" onClick={()=>setContext(undefined)}><X/></button></div>
 {context.text&&<blockquote className="selected-passage">{context.text}</blockquote>}
 <div className="assistant-log" ref={log}>{messages.map((m,i)=><div className={'chat-message '+m.role} key={i}><strong>{m.role==='user'?'你':'学习助手'}</strong><Markdown text={m.content}/>{m.needs_human_review&&<span className="badge amber">回答存在不确定性</span>}<ReviewAdvice review={m.ai_review}/></div>)}{pending&&<p role="status">正在结合学习记录分析…</p>}</div>
 <form onSubmit={e=>{e.preventDefault();if(working)return;setPending(true);sent.current=context.unit_id;action('chat',{unit_id:context.unit_id,selected_text:context.text,surrounding_text:context.context,message:message.trim()||'请结合我的学习记录解释划选内容，并指出容易混淆的地方。',hint_level:level});}}>
 <SymbolInput aria-label="向学习助手提问" topic={course.topic} rows={3} value={message} onChange={value=>{setMessage(value);localStorage.setItem(draftKey(context.unit_id),value);}} placeholder="补充你的疑问"/>
 <div className="form-footer"><select aria-label="讲解深度" value={level} onChange={e=>setLevel(Number(e.target.value))}><option value={1}>提示方向</option><option value={2}>关键步骤</option><option value={3}>详细解释</option></select><button className="primary small" disabled={working||(!context.text&&!message.trim())}><Send size={16}/> 发送问题</button></div></form>
 </aside></div>}</>;
}
