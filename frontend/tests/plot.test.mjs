import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import ts from 'typescript';
const source = readFileSync(new URL('../src/Plot.tsx', import.meta.url), 'utf8');
const parser = source.slice(source.indexOf('export function sample'), source.indexOf('export default function Plot'));
const { outputText } = ts.transpileModule(parser, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext } });
const { sample } = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
test('plot parser respects mathematical precedence and backend exponent syntax', () => {
  assert.equal(sample('-x^2', 3), -9);
  assert.equal(sample('2^3^2', 0), 512);
  assert.equal(sample('x**2 + sqrt(4)', 3), 11);
  assert.equal(sample('2^-2', 0), .25);
  assert.ok(Math.abs(sample('sin(pi/2)', 0) - 1) < 1e-12);
});
test('plot parser rejects executable text, implicit multiplication, and excessive input', () => {
  for (const input of ['alert(1)', 'x.constructor', '2x', '(()=>1)()', '('.repeat(45)+'1'+')'.repeat(45), '1+'.repeat(200)+'1']) {
    assert.throws(() => sample(input, 2), undefined, input);
  }
});
