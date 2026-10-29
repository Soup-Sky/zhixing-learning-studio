export type SymbolKey={label?:string;text:string;cursor?:number;title?:string};
export type SymbolGroup={name:string;symbols:SymbolKey[]};
export function insertSymbol(value:string,start:number,end:number,symbol:SymbolKey){
 return {value:value.slice(0,start)+symbol.text+value.slice(end),cursor:start+(symbol.cursor??symbol.text.length)};
}
const keys=(text:string):SymbolKey[]=>text.split(' ').map(text=>({text}));
export function symbolGroups(topic:string):SymbolGroup[]{
 const groups:SymbolGroup[]=[
  {name:'常用',symbols:[...keys('+ − × ÷ = ≠ ≤ ≥ ± ∞ → ∈ ∉ ∪ ∩'),
   {label:'√',text:'sqrt()',cursor:5,title:'平方根 sqrt()'},
   {label:'x²',text:'^2',title:'平方'}, {label:'xⁿ',text:'^()',cursor:2,title:'幂'},
   {label:'a/b',text:'()/()',cursor:1,title:'分式'},...keys('∑ ∫ ∂ ∇')]},
  {name:'希腊字母',symbols:keys('α β γ δ ε θ λ μ π σ φ ψ ω Δ Σ Ω')},
  {name:'公式模板',symbols:[{label:'sin',text:'sin()',cursor:4},{label:'cos',text:'cos()',cursor:4},
   {label:'ln',text:'log()',cursor:4},{label:'|x|',text:'abs()',cursor:4},
   {label:'[a,b]',text:'[,]',cursor:1},{label:'LaTeX',text:'$$',cursor:1}]},
 ];
 if(/化学|chemistry|chemical/i.test(topic))groups.unshift({name:'化学',symbols:keys('⇌ → ↑ ↓ ₀ ₁ ₂ ₃ ₄ ₅ ₆ ₇ ₈ ₉ ⁺ ⁻ ·')});
 if(/物理|physics/i.test(topic))groups.unshift({name:'物理',symbols:keys('Δ ∇ ∂ ℏ Å Ω μ ε ρ τ ν θ °')});
 if(/统计|概率|statistics|probability/i.test(topic))groups.unshift({name:'统计',symbols:keys('μ σ Σ ∼ ≈ ∩ ∪ ∈ ℙ 𝔼')});
 if(/日语|japanese/i.test(topic))groups.unshift({name:'日语',symbols:keys('あ い う え お か き く け こ し つ ん ア イ ウ エ オ ー 「 」')});
 if(/英语|english|法语|french|德语|german|语言/i.test(topic))groups.unshift({name:'语言',symbols:keys('é è ê à ç ü ö ä ß æ œ ñ ¿ ¡ ə ʃ θ ð ŋ')});
 if(/编程|代码|program|python|javascript/i.test(topic))groups.unshift({name:'代码',symbols:keys('{ } [ ] ( ) < > = _ : ; / \\ | & ! # @')});
 return groups;
}
