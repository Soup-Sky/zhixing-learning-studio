import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {renderToStaticMarkup} from 'react-dom/server';
import {createElement} from 'react';
import ts from 'typescript';

const source = readFileSync(new URL('../src/Markdown.tsx', import.meta.url), 'utf8');
let {outputText} = ts.transpileModule(source, {compilerOptions: {
 target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
}});
outputText = outputText.replace(/from (['"])([^'"]+)\1/g, (_match, _quote, name) => {
 const url = import.meta.resolve(name.startsWith('.') ? '../src/' + name.slice(2) + '.ts' : name);
 return 'from ' + JSON.stringify(url);
});
// TypeScript dependencies are loaded through the same transpilation as the app.
if (outputText.includes('/mathText.ts')) {
 const mathSource = readFileSync(new URL('../src/mathText.ts', import.meta.url), 'utf8');
 const mathCode = ts.transpileModule(mathSource, {compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext,
 }}).outputText;
 const moduleUrl = 'data:text/javascript;base64,' + Buffer.from(mathCode).toString('base64');
 outputText = outputText.replace(/file:[^"']+\/mathText\.ts/g, moduleUrl);
}
const {default: Markdown} = await import('data:text/javascript;base64,' + Buffer.from(outputText).toString('base64'));
const render = text => renderToStaticMarkup(createElement(Markdown, {text}));

test('customer limit prompt renders a limit and powers rather than raw notation', () => {
 const html = render('计算极限：lim_{x→0} (e^x - 1 - x) / x^2。请给出精确值。');
 assert.match(html, /class="katex"/);
 assert.match(html, /\\lim/);
 assert.doesNotMatch(html, /katex-error/);
 assert.match(html, /请给出精确值/);
});

test('customer polynomial and interval render without changing the question', () => {
 const html = render('设 f(x) = x^3 - 3x + 1。求 f 在闭区间 [-2, 2] 上的最大值与最小值，并说明取得位置。');
 assert.match(html, /class="katex"/);
 assert.doesNotMatch(html, /katex-error/);
 assert.match(html, /最大值与最小值/);
 assert.match(html, /<annotation encoding="application\/x-tex">\[-2, 2\]<\/annotation>/);
});

test('model parenthesis and bracket math delimiters render', () => {
 const html = render(String.raw`先看 \(x^2\)，再看 \[\frac{1}{2}\]。`);
 assert.match(html, /class="katex"/);
 assert.match(html, /katex-display/);
 assert.doesNotMatch(html, /katex-error/);
});

test('existing dollar math renders while code, URLs, currency and prose stay intact', () => {
 const html = render('正常公式 $x^2$。代码 `x^2`。\n\n```python\nf(x)=x**2\n```\n\n[参考资料](https://example.com/x^2)\n\n费用 20 元，价格 \\$5；Find f(x)=x^2 in the lesson.');
 assert.match(html, /<code>x\^2<\/code>/);
 assert.match(html, /f\(x\)=x\*\*2/);
 assert.match(html, /href="https:\/\/example.com\/x%5E2"/);
 assert.match(html, /价格 \$5/);
 assert.match(html, /in the lesson/);
 assert.doesNotMatch(html, /katex-error/);
});
