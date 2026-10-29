import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/plan.ts', import.meta.url), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { planUnits, percentageScore, feedbackTitle, courseStatusLabel, masteryPercent, reviewGroups } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
test('learning map follows planned scope and graph order, not the full catalog', () => {
 const units = [{id:'limits'}, {id:'derivatives'}, {id:'integrals'}];
 assert.deepEqual(planUnits({units}), units);
 assert.deepEqual(planUnits({units,plan:{unit_order:['derivatives','limits']}}).map(u=>u.id), ['derivatives','limits']);
 assert.deepEqual(planUnits({units,plan:{unit_order:[]}}), []);
 assert.deepEqual(planUnits({units,plan:{unit_order:['unknown']}}), []);
});
test('teacher percentages normalize once for API scores and reject out-of-range values', () => {
 assert.equal(percentageScore('80'), .8);
 assert.equal(percentageScore('0'), 0);
 assert.equal(percentageScore('100'), 1);
 assert.equal(percentageScore(''), undefined);
 for(const invalid of ['-1','101','NaN','Infinity']) assert.throws(()=>percentageScore(invalid));
});
test('previous assignment feedback is labeled as previous after remedial questions replace it', () => {
 assert.equal(feedbackTitle({assignment:{id:'new'},history:[{assignment_id:'old'}]}), '上一次练习的反馈');
 assert.equal(feedbackTitle({assignment:{id:'current'},history:[{assignment_id:'current'}]}), '这次练习的反馈');
});
test('course status and mastery percentage are shown in plain Chinese and stay in range', () => {
 assert.equal(courseStatusLabel('active'), '学习中');
 assert.equal(courseStatusLabel('diagnostic'), '待完成起点测评');
 assert.equal(courseStatusLabel(undefined), '未开始');
 assert.equal(masteryPercent(1, 3), 33);
 assert.equal(masteryPercent(0, 0), 0);
 assert.equal(masteryPercent(5, 4), 100);
});
test('notebook items split into due, scheduled and mastered by parsed time, not string order', () => {
 const now = Date.parse('2026-10-22T12:00:00Z');
 const groups = reviewGroups([
  {id:'a', next_due:'2026-10-22T11:00:00+00:00'},
  {id:'b', next_due:'2026-10-22T20:00:00+08:00'},
  {id:'c', next_due:'2026-10-23T00:00:00+00:00'},
  {id:'d', next_due:null},
 ], now);
 assert.deepEqual(groups.due.map(i=>i.id), ['a','b']);
 assert.deepEqual(groups.later.map(i=>i.id), ['c']);
 assert.deepEqual(groups.done.map(i=>i.id), ['d']);
});
