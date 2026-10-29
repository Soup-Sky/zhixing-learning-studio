// Compatibility for existing model output. This formats notation only; it never
// evaluates an answer or changes the expression sent to mathematical grading.
const protectedText = /```[\s\S]*?```|~~~[\s\S]*?~~~|`+[^`\n]*`+|\$\$[\s\S]*?\$\$|(?<!\\)\$[^$\n]*?(?<!\\)\$|!?\[[^\]\n]*\]\([^\n]*?\)|https?:\/\/[^\s]+|\\\$|\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]/g;
const bareFormula = /(?<![A-Za-z0-9_\\])(?:\[[ \t]*[+-]?\d+(?:\.\d+)?[ \t]*,[ \t]*[+-]?\d+(?:\.\d+)?[ \t]*\]|\\(?:lim|frac|sqrt|sum|int)\b|lim(?=[_({])|[A-Za-z]['′]?(?:\([^()\n]*\))?[ \t]*(?:[=<>≤≥≠^²³⁴⁵⁶⁷⁸⁹]|\*\*))[A-Za-z0-9_{}()[\]\\^*+\-/=<>≤≥≠→∞π²³⁴⁵⁶⁷⁸⁹⁰¹.,'′| \t]*/g;
const mathWords = new Set(['lim', 'frac', 'sqrt', 'sin', 'cos', 'tan', 'log', 'ln',
 'exp', 'abs', 'pi', 'infty', 'to', 'left', 'right', 'cdot', 'times', 'sum', 'int',
 'alpha', 'beta', 'gamma', 'theta', 'epsilon', 'delta', 'le', 'ge', 'ne']);

function latex(expression: string): string {
 return expression.replace(/\*\*/g, '^').replace(/\*/g, String.raw`\cdot `)
  .replace(/→/g, String.raw`\to `).replace(/∞/g, String.raw`\infty `)
  .replace(/π/g, String.raw`\pi `).replace(/≤/g, String.raw`\le `)
  .replace(/≥/g, String.raw`\ge `).replace(/≠/g, String.raw`\ne `)
  .replace(/[⁰¹²³⁴⁵⁶⁷⁸⁹]+/g, digits => '^{'+[...digits].map(d => '⁰¹²³⁴⁵⁶⁷⁸⁹'.indexOf(d)).join('')+'}')
  .replace(/\^\(([^()]*)\)/g, '^{$1}')
  .replace(/(?<!\\)\bsqrt\(([^()]*)\)/g, String.raw`\sqrt{$1}`)
  .replace(/(?<!\\)\b(lim|sin|cos|tan|log|ln|exp)(?=[_({]|\b)/g, String.raw`\$1`);
}

function plainText(text: string): string {
 return text.replace(bareFormula, candidate => {
  // Do not pull English prose into a mathematical environment.
  const word = [...candidate.matchAll(/[A-Za-z]{2,}/g)].find(m => !mathWords.has(m[0]));
  const end = word?.index ?? candidate.length;
  const expression = candidate.slice(0, end).replace(/[\s.,]+$/, '');
  if (!expression || !/[=<>^²³⁴⁵⁶⁷⁸⁹]|lim|\\(?:frac|sqrt|sum|int)|^\[.*\]$/.test(expression)) return candidate;
  const stack: string[] = [];
  for (const char of expression) {
   if ('({['.includes(char)) stack.push(char);
   else if (')}]'.includes(char) && stack.pop() !== ({')':'(', '}':'{', ']':'['}[char])) return candidate;
  }
  if (stack.length) return candidate;
  return '$'+latex(expression)+'$'+candidate.slice(expression.length);
 });
}

export function mathMarkdown(text: string): string {
 let result = '', offset = 0;
 for (const match of text.matchAll(protectedText)) {
  const start = match.index!;
  result += plainText(text.slice(offset, start));
  const part = match[0];
  if (part.startsWith(String.raw`\(`)) result += '$'+latex(part.slice(2, -2))+'$';
  else if (part.startsWith(String.raw`\[`)) result += '\n\n$$\n'+latex(part.slice(2, -2))+'\n$$\n\n';
  else result += part;
  offset = start + part.length;
 }
 return result + plainText(text.slice(offset));
}
