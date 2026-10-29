// Offline browser check of 1.3.1: setup/login, key settings, stage test, notebook, progress,
// materials, practice feedback, appeal, teacher review, admin progress and backup, learner isolation, mobile layout and the web exit button. Uses the local Edge over
// CDP (no Playwright) and scripts/e2e_server.py (temporary database, stubbed DeepSeek, no network).
// Run from rebuild/: node scripts/verify_accounts_browser.mjs
import {spawn} from 'node:child_process';
import {existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync} from 'node:fs';
import {tmpdir} from 'node:os';
import path from 'node:path';
import readline from 'node:readline';
import {fileURLToPath} from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const python = path.join(root, '.venv', 'Scripts', 'python.exe');
const edgePath = process.env.EDGE_PATH || 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const shots = path.join(root, 'evidence', 'ui-1.3.1');
const sleep = ms => new Promise(resolve => setTimeout(resolve, ms));

function startServer() {
  const child = spawn(python, [path.join(root, 'scripts', 'e2e_server.py')], {cwd: root, env: {...process.env, PYTHONUTF8: '1'}});
  child.stderr.on('data', data => process.stderr.write(data));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('测试服务未启动')), 90000);
    readline.createInterface({input: child.stdout}).on('line', line => {
      try { const info = JSON.parse(line); clearTimeout(timer); resolve({child, ...info}); } catch { /* not the ready line */ }
    });
    child.on('exit', code => reject(new Error('测试服务退出：' + code)));
  });
}

async function startEdge() {
  const profile = mkdtempSync(path.join(tmpdir(), 'zhixing-edge-'));
  const child = spawn(edgePath, ['--headless=new', '--disable-gpu', '--no-first-run', '--no-default-browser-check',
    '--remote-debugging-port=0', '--user-data-dir=' + profile, 'about:blank'], {stdio: 'ignore'});
  const portFile = path.join(profile, 'DevToolsActivePort');
  for (let i = 0; i < 300 && !existsSync(portFile); i++) await sleep(100);
  const port = readFileSync(portFile, 'utf8').split('\n')[0].trim();
  let target;
  for (let i = 0; i < 100 && !target; i++) {
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(t => t.type === 'page'); } catch { /* retry */ }
    if (!target) await sleep(100);
  }
  return {child, profile, ws: target.webSocketDebuggerUrl};
}

class CDP {
  constructor(url) {
    this.ws = new WebSocket(url); this.id = 0; this.pending = new Map(); this.handlers = [];
    this.ws.onmessage = ({data}) => {
      const message = JSON.parse(data);
      if (message.id) {
        const waiter = this.pending.get(message.id); this.pending.delete(message.id);
        message.error ? waiter.reject(new Error(message.error.message)) : waiter.resolve(message.result);
      } else this.handlers.forEach(handler => handler(message));
    };
    this.ready = new Promise((resolve, reject) => { this.ws.onopen = resolve; this.ws.onerror = reject; });
  }
  send(method, params = {}) {
    const id = ++this.id;
    this.ws.send(JSON.stringify({id, method, params}));
    return new Promise((resolve, reject) => this.pending.set(id, {resolve, reject}));
  }
}

// Injected before page scripts: auto-accepts confirm() and fills React-controlled fields.
const HELPERS = `
window.confirm = () => true;
window.__e2e = {
  fill(selector, value, index = 0) {
    const el = document.querySelectorAll(selector)[index];
    if (!el) throw new Error('missing ' + selector);
    const proto = el instanceof HTMLTextAreaElement ? HTMLTextAreaElement : el instanceof HTMLSelectElement ? HTMLSelectElement : HTMLInputElement;
    Object.getOwnPropertyDescriptor(proto.prototype, 'value').set.call(el, value);
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    return true;
  },
  fillAll(selector, value) { const n = document.querySelectorAll(selector).length; for (let i = 0; i < n; i++) this.fill(selector, value, i); return n; },
  click(text, scope = 'body') {
    const el = [...document.querySelectorAll(scope + ' button, ' + scope + ' a')].find(e => e.textContent.trim().includes(text) && !e.disabled);
    if (!el) throw new Error('no button ' + text);
    el.click(); return true;
  },
  clickSelector(selector) { const el = document.querySelector(selector); if (!el) throw new Error('missing ' + selector); el.click(); return true; },
};`;

const steps = [], exceptions = [], consoleErrors = [];
let cdp;
const evaluate = async expression => {
  const r = await cdp.send('Runtime.evaluate', {expression, awaitPromise: true, returnByValue: true});
  if (r.exceptionDetails) throw new Error('页面脚本出错：' + (r.exceptionDetails.exception?.description || r.exceptionDetails.text));
  return r.result.value;
};
const call = (fn, ...args) => evaluate(`window.__e2e.${fn}(${args.map(a => JSON.stringify(a)).join(',')})`);
async function waitFor(expression, label, timeout = 15000) {
  const end = Date.now() + timeout;
  while (Date.now() < end) { if (await evaluate(expression)) return; await sleep(150); }
  throw new Error('等待超时：' + label);
}
const has = text => `document.body.innerText.includes(${JSON.stringify(text)})`;
const waitText = (text, timeout) => waitFor(has(text), text, timeout);
async function shot(name) {
  // Long-lived success notices can cover the content being captured; close them first.
  await evaluate(`(() => {document.querySelectorAll('.operation-feedback .icon-button').forEach(button => button.click()); return true;})()`);
  await sleep(120);
  const {data} = await cdp.send('Page.captureScreenshot', {format: 'png'});
  writeFileSync(path.join(shots, name + '.png'), Buffer.from(data, 'base64'));
}
async function step(name, work) {
  const started = Date.now();
  try { await work(); steps.push({name, ok: true, ms: Date.now() - started}); }
  catch (error) { steps.push({name, ok: false, error: String(error.message || error)}); throw error; }
}
const viewport = (width, height) => cdp.send('Emulation.setDeviceMetricsOverride', {width, height, deviceScaleFactor: 1, mobile: width < 700});

mkdirSync(shots, {recursive: true});
const server = await startServer();
const edge = await startEdge();
const base = `http://127.0.0.1:${server.port}/`;
let serverStopped = false;
server.child.on('exit', () => { serverStopped = true; });
try {
  cdp = new CDP(edge.ws); await cdp.ready;
  cdp.handlers.push(m => {
    if (m.method === 'Runtime.exceptionThrown') exceptions.push(m.params.exceptionDetails.exception?.description || m.params.exceptionDetails.text);
    if (m.method === 'Runtime.consoleAPICalled' && m.params.type === 'error') consoleErrors.push(m.params.args.map(a => a.value ?? a.description).join(' '));
  });
  await cdp.send('Runtime.enable'); await cdp.send('Page.enable');
  await cdp.send('Page.addScriptToEvaluateOnNewDocument', {source: HELPERS});
  await viewport(1440, 960);
  await cdp.send('Page.navigate', {url: base});

  await step('首次打开显示“创建管理员账号”，无需启动窗口', async () => {
    await waitText('创建管理员账号'); await shot('01-setup');
    await call('fill', 'input[name=username]', 'admin'); await call('fill', 'input[name=display_name]', '管理员');
    await call('fill', 'input[name=password]', 'admin-pass-1'); await call('fill', 'input[name=confirm]', 'admin-pass-1');
    await call('click', '创建并进入');
    await waitText('微积分：从函数到极限'); await waitText('填写 DeepSeek 密钥');
  });
  await step('新建主题：每周小时默认 3 可用', async () => {
    await call('click', '新建主题', '.sidebar');
    await waitText('开始新的学习主题');
    const hours = await evaluate(`(() => {const el=document.querySelector('input[name=hours]');return {value:el.value,valid:el.checkValidity(),step:el.step};})()`);
    if (hours.value !== '3' || hours.valid !== true || hours.step !== 'any') throw new Error('每周小时默认值不可用：' + JSON.stringify(hours));
    await call('clickSelector', '.modal-close');
  });
  await step('设置页：错误密钥被拒绝且不保存，正确密钥验证后保存', async () => {
    await call('click', '设置与账号', '.sidebar'); await waitText('尚未配置');
    await call('fill', 'input[name=api_key]', 'sk-wrong-key-for-e2e-000000'); await call('click', '验证并保存');
    await waitFor(`document.querySelector('.form-error')?.innerText.includes('拒绝')`, '拒绝提示');
    if (!await evaluate(has('尚未配置'))) throw new Error('错误密钥后状态不应变为已配置');
    await call('fill', 'input[name=api_key]', server.stub_key); await call('click', '验证并保存');
    await waitText('已通过 DeepSeek 验证并保存'); await waitText('AI 服务已连接');
    await waitText('learning.sqlite'); await waitText('次调用');
  });
  await step('管理员添加学习者账号', async () => {
    const form = 'form[aria-label="添加账号"]';
    await call('fill', form + ' input[name=username]', 'student'); await call('fill', form + ' input[name=password]', 'student-pass-1');
    await call('click', '添加账号', form); await waitText('账号已创建');
    await shot('02-settings');
  });
  await step('阶段测验：12 题提交并显示批改结果与历史', async () => {
    await call('click', '微积分：从函数到极限', '.sidebar'); await waitText('知识地图');
    await call('click', '阶段测验', '.lesson-tabs');
    await waitFor(`document.querySelectorAll('.assessment-panel .question').length === 12`, '12 道测验题');
    await call('fillAll', '.assessment-panel textarea', '1'); await call('click', '提交测验', '.assessment-panel');
    await waitText('测验结果', 180000); await waitText('前测（学习前） ·');
    await shot('03-assessment');
  });
  await step('错题本：待复习角标、重新作答、批改后移到“之后复习”', async () => {
    await waitFor(`document.querySelector('.nav-badge')?.innerText === '1'`, '待复习角标 1');
    await call('click', '错题本', '.sidebar'); await waitText('今天该复习'); await shot('04-notebook');
    await call('click', '重新作答'); await call('fill', '.note-item textarea', server.notebook_answer);
    await call('click', '提交批改'); await waitText('复习结果', 120000);
    await waitFor(`!${has('今天该复习')} && ${has('之后复习')}`, '答对后移到之后复习');
    await waitFor(`!document.querySelector('.nav-badge')`, '角标消失');
  });
  await step('学习进度：中文状态与掌握统计', async () => {
    await call('click', '学习进度', '.sidebar'); await waitText('1 / 6 单元'); await waitText('学习中');
    if (await evaluate(has('active'))) throw new Error('状态仍显示英文');
    await shot('05-progress');
  });
  await step('学习资料：内置教材标为共享', async () => {
    await call('click', '学习资料', '.sidebar'); await waitText('内置共享'); await shot('06-sources');
  });
  await step('练习：提交开放题后不刷新页面即显示反馈', async () => {
    await call('click', '微积分：从函数到极限', '.sidebar'); await waitText('知识地图');
    await call('click', '练习', '.lesson-tabs');
    await waitFor(`!!document.querySelector('.learning-surface textarea')`, '练习题');
    await call('fill', '.learning-surface textarea', '极限描述自变量趋近某点时函数值的趋势。');
    await call('click', '提交答案', '.learning-surface');
    await waitText('第 1 题 · 60 分', 60000); await waitText('AI 已审核 · 建议核对');
    await shot('07-feedback');
  });
  await step('申诉：AI 重新批改本题并保留原分', async () => {
    await call('click', '对本题评分有疑问', '.feedback-view');
    await call('fill', '.appeal-form textarea', '我写出了趋近过程，希望再核对一次。');
    await call('click', '请 AI 重新批改', '.appeal-form');
    await waitText('已申诉：AI 重新批改 60 → 70 分', 60000); await waitText('（原 60 分）');
    await shot('08-appeal');
  });
  await step('教师审核：列出 AI 建议核对的记录，改分后重新计算进度', async () => {
    await call('click', '教师审核', '.sidebar'); await waitText('学习者申诉'); await waitText('练习评分');
    await shot('09-teacher');
    await call('fill', 'input[aria-label="新的分数（0–100）"]', '90');
    await call('click', '改分', '.review-card');
    await waitText('已改分，学员的掌握进度已重新计算。', 30000);
    const mastered = await evaluate(`fetch('/api/courses/demo-calculus').then(r=>r.json()).then(c=>c.mastery.u02.status)`);
    if (mastered !== 'mastered') throw new Error('改分后掌握状态为 ' + mastered);
  });
  await step('学员进度与备份：只含统计，备份是 SQLite 文件', async () => {
    await call('click', '学员进度', '.lesson-tabs'); await waitText('待复习错题'); await waitText('还没有课程');
    await shot('10-learner-progress');
    const head = await evaluate(`fetch('/api/admin/backup').then(r=>r.arrayBuffer()).then(b=>new TextDecoder().decode(new Uint8Array(b).slice(0,15)))`);
    if (head !== 'SQLite format 3') throw new Error('备份文件头为 ' + head);
    const logs = await evaluate(`fetch('/api/admin/logs').then(r=>r.status)`);
    if (logs !== 200) throw new Error('错误日志返回 ' + logs);
  });
  await step('学习者登录后看不到管理员的课程、密钥设置和参考答案', async () => {
    await call('clickSelector', '[aria-label="退出登录"]');
    await waitFor(`document.querySelector('#auth-title')?.innerText === '登录'`, '登录页');
    await call('fill', 'input[name=username]', 'student'); await call('fill', 'input[name=password]', 'student-pass-1');
    await call('click', '登录'); await waitText('开始新学习'); await waitText('AI 服务已连接');
    if (await evaluate(has('微积分：从函数到极限'))) throw new Error('学习者看到了管理员课程');
    const codes = await evaluate(`Promise.all(['/api/courses/demo-calculus','/api/teacher/courses/demo-calculus/trace','/api/users','/api/teacher/reviews','/api/admin/progress','/api/admin/backup','/api/admin/logs'].map(u=>fetch(u).then(r=>r.status)))`);
    if (codes.join() !== '404,403,403,403,403,403,403') throw new Error('越权请求返回 ' + codes.join());
    await call('click', '账号设置', '.sidebar'); await waitText('我的账号');
    if (await evaluate(has('DeepSeek API 密钥'))) throw new Error('学习者看到了密钥设置');
    if (await evaluate(has('教师审核'))) throw new Error('学习者看到了教师审核入口');
    await shot('11-learner');
  });
  await step('手机宽度 390px：导航可展开、设置页无横向溢出', async () => {
    await call('clickSelector', '[aria-label="退出登录"]');
    await waitFor(`document.querySelector('#auth-title')?.innerText === '登录'`, '登录页');
    await call('fill', 'input[name=username]', 'admin'); await call('fill', 'input[name=password]', 'admin-pass-1');
    await call('click', '登录'); await waitText('知识地图');
    await viewport(390, 844); await sleep(300);
    await call('clickSelector', '.mobile-toggle'); await call('click', '设置与账号', '.sidebar');
    await waitText('DeepSeek API 密钥');
    await waitFor(`document.documentElement.scrollWidth <= innerWidth`, '无横向溢出');
    await shot('12-mobile-settings');
    await viewport(1440, 960);
  });
  await step('网页“退出程序”真正停止本机服务', async () => {
    await call('click', '退出程序'); await waitText('程序已退出');
    for (let i = 0; i < 100 && !serverStopped; i++) await sleep(100);
    if (!serverStopped) throw new Error('服务进程仍在运行');
  });
} catch (error) {
  try { await shot('failure'); console.error((await evaluate('document.body.innerText')).slice(0, 1500)); } catch { /* page gone */ }
  console.error(error);
} finally {
  edge.child.kill(); if (!serverStopped) server.child.kill();
  await sleep(500);
  rmSync(edge.profile, {recursive: true, force: true, maxRetries: 5, retryDelay: 300});
}
const ok = steps.length === 15 && steps.every(s => s.ok) && exceptions.length === 0;
writeFileSync(path.join(root, 'evidence', 'browser-accounts-offline.json'), JSON.stringify({
  kind: 'offline_browser_check', version: '1.3.1', at: new Date().toISOString(), ok,
  method: '本机 Edge 无头模式 + CDP；scripts/e2e_server.py 使用临时数据库、内存密钥库和 DeepSeek 离线桩，不联网。',
  limits: '只验证页面流程、权限和接线；批改分数来自离线桩与 SymPy，不代表真实模型质量、教学效果或真人学习增益。',
  steps, page_exceptions: exceptions, console_errors: consoleErrors,
  screenshots: 'evidence/ui-1.3.1/*.png（界面示例）',
}, null, 1), 'utf8');
for (const s of steps) console.log((s.ok ? 'PASS ' : 'FAIL ') + s.name + (s.error ? ' — ' + s.error : ''));
console.log(ok ? '浏览器检查全部通过' : '浏览器检查未通过');
process.exitCode = ok ? 0 : 1;
