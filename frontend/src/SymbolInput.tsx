import {useRef,useState} from 'react';
import type {TextareaHTMLAttributes} from 'react';
import {Keyboard,X} from 'lucide-react';
import {insertSymbol,symbolGroups} from './symbols';
import type {SymbolKey} from './symbols';

type Props=Omit<TextareaHTMLAttributes<HTMLTextAreaElement>,'value'|'onChange'> & {
 value:string;onChange:(value:string)=>void;topic?:string;
};
export default function SymbolInput({value,onChange,topic='',...props}:Props){
 const [open,setOpen]=useState(false),[group,setGroup]=useState(0);
 const input=useRef<HTMLTextAreaElement>(null);
 const selection=useRef({start:value.length,end:value.length});
 const groups=symbolGroups(topic);
 const remember=()=>{if(input.current)selection.current={start:input.current.selectionStart,end:input.current.selectionEnd};};
 const insert=(symbol:SymbolKey)=>{
  const result=insertSymbol(value,selection.current.start,selection.current.end,symbol);
  onChange(result.value);selection.current={start:result.cursor,end:result.cursor};
  requestAnimationFrame(()=>{input.current?.focus();input.current?.setSelectionRange(result.cursor,result.cursor);});
 };
 return <div className="symbol-input"><textarea {...props} ref={input} value={value}
  onChange={e=>{onChange(e.target.value);remember();}} onSelect={remember} onBlur={remember}/>
  <div className="input-tools"><button type="button" className="icon-button" title="常用字符" aria-label="常用字符" aria-expanded={open}
   disabled={props.disabled} onMouseDown={e=>e.preventDefault()} onClick={()=>setOpen(!open)}><Keyboard size={19}/></button></div>
  {open&&<section className="symbol-panel" aria-label="字符面板"><div className="symbol-tabs">{groups.map((g,i)=><button key={g.name} type="button" className={group===i?'selected':''} onMouseDown={e=>e.preventDefault()} onClick={()=>setGroup(i)}>{g.name}</button>)}<button type="button" className="icon-button" aria-label="关闭字符面板" onClick={()=>setOpen(false)}><X size={16}/></button></div>
   <div className="symbol-grid">{(groups[group]||groups[0]).symbols.map((s,i)=><button type="button" key={i} title={s.title||s.text} aria-label={s.title||s.label||s.text} onMouseDown={e=>e.preventDefault()} onClick={()=>insert(s)}>{s.label||s.text}</button>)}</div></section>}
 </div>;
}
