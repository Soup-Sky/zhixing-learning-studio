import ReactMarkdown from 'react-markdown';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import {mathMarkdown} from './mathText';
export default function Markdown({text}:{text:string}){return <div className="markdown"><ReactMarkdown remarkPlugins={[remarkMath]} rehypePlugins={[rehypeKatex]}>{mathMarkdown(text||'')}</ReactMarkdown></div>;}
