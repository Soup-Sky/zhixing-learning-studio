import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import ts from 'typescript';
const code=ts.transpileModule(readFileSync(new URL('../src/symbols.ts',import.meta.url),'utf8'),{
 compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ESNext},
}).outputText;
const {insertSymbol,symbolGroups}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));

test('symbol insertion replaces selection and places cursor inside templates',()=>{
 assert.deepEqual(insertSymbol('abc',1,2,{text:'π'}),{value:'aπc',cursor:2});
 assert.deepEqual(insertSymbol('x+',2,2,{text:'sqrt()',cursor:5}),{value:'x+sqrt()',cursor:7});
 assert.deepEqual(insertSymbol('',0,0,{text:'α'}),{value:'α',cursor:1});
});
test('subject panels include math and subject-specific characters',()=>{
 assert.ok(symbolGroups('微积分').flatMap(g=>g.symbols).some(s=>s.label==='√'));
 assert.ok(symbolGroups('化学').flatMap(g=>g.symbols).some(s=>s.text==='⇌'));
 assert.ok(symbolGroups('日语').flatMap(g=>g.symbols).some(s=>s.text==='あ'));
});
