import type {Course,Unit} from './api';
export function planUnits(course?:Pick<Course,'units'|'plan'>):Unit[]{
 if(!course)return [];
 if(!course.plan)return course.units;
 const units=new Map(course.units.map(unit=>[unit.id,unit]));
 return course.plan.unit_order.map(id=>units.get(id)).filter((unit):unit is Unit=>!!unit);
}
export function percentageScore(value:string):number|undefined{
 if(value.trim()==='')return undefined;
 const number=Number(value);
 if(!Number.isFinite(number)||number<0||number>100)throw Error('修订分数必须在 0–100 之间');
 return number/100;
}
export function courseStatusLabel(status?:string):string{
 const labels:Record<string,string>={diagnostic:'待完成起点测评',active:'学习中',completed:'已完成'};
 return labels[status||'']||status||'未开始';
}
export function masteryPercent(mastered:number,planned:number):number{
 return planned>0?Math.min(100,Math.round(mastered/planned*100)):0;
}
// Notebook items without a next due date have been answered correctly three times.
export function reviewGroups<T extends {next_due?:string|null}>(items:T[],now=Date.now()):{due:T[];later:T[];done:T[]}{
 const groups={due:[] as T[],later:[] as T[],done:[] as T[]};
 for(const item of items){
  if(!item.next_due)groups.done.push(item);
  else if(Date.parse(item.next_due)<=now)groups.due.push(item);
  else groups.later.push(item);
 }
 return groups;
}
export function feedbackTitle(course:Pick<Course,'assignment'|'history'>):string{
 const previous=course.history?.at(-1);
 return previous&&course.assignment?.id!==previous.assignment_id?'上一次练习的反馈':'这次练习的反馈';
}
