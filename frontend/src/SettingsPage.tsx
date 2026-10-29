import { useCallback, useEffect, useState } from "react";
import { Database, Download, FileWarning, Info, KeyRound, LoaderCircle, Power, Settings, Trash2, UserPlus, Users } from "lucide-react";
import { ApiError, api } from "./api";
import type { ProviderState, SystemInfo, User } from "./api";

const SOURCE: Record<string, string> = {
  vault: "已保存在 Windows 凭据管理器，下次启动自动使用",
  session: "仅本次运行有效，退出程序后需重新填写",
  env: "来自 DEEPSEEK_API_KEY 环境变量",
};

// work may return a string to replace the default success notice.
type Run = (work: () => Promise<unknown>, done?: string) => Promise<boolean>;

export default function SettingsPage({
  user,
  onUser,
  onStatus,
}: {
  user: User;
  onUser: (user: User) => void;
  onStatus: () => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [stopped, setStopped] = useState(false),
    [info, setInfo] = useState<SystemInfo>();
  useEffect(() => {
    api<SystemInfo>("/system/info").then(setInfo).catch(() => undefined);
  }, []);
  // One feedback line for the whole page keeps screen-reader announcements predictable.
  const run: Run = async (work, done) => {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const message = await work();
      if (typeof message === "string" || done) setNotice(typeof message === "string" ? message : done!);
      return true;
    } catch (e) {
      setError(e instanceof Error ? e.message : "操作失败");
      return false;
    } finally {
      setBusy(false);
    }
  };
  if (stopped)
    return (
      <div className="manage-page">
        <h1>程序已退出</h1>
        <p>本机服务已停止，学习记录已保存。可以关闭此页面；下次双击程序即可继续。</p>
      </div>
    );
  return (
    <div className="manage-page">
      <h1>
        <Settings /> 设置
      </h1>
      {error && <p className="form-error" role="alert">{error}</p>}
      {notice && <p className="form-notice" role="status">{notice}</p>}
      <Profile user={user} busy={busy} run={run} onUser={onUser} />
      {user.role === "admin" && (
        <>
          <Provider busy={busy} run={run} onStatus={onStatus} />
          <Accounts me={user} busy={busy} run={run} />
        </>
      )}
      <About info={info} admin={user.role === "admin"} />
      {user.role === "admin" && info?.can_shutdown && (
        <>
          <section className="manage-card settings-section">
            <h2>
              <Power size={18} /> 退出程序
            </h2>
            <p className="muted">停止本机服务。所有账号的学习记录都会保留；正在进行的生成任务会中断。</p>
            <button
              className="secondary danger"
              disabled={busy}
              onClick={() =>
                window.confirm("退出知行学习工作室？") &&
                run(() => api("/system/shutdown", {})).then((ok) => ok && setStopped(true))
              }
            >
              <Power size={16} /> 退出程序
            </button>
          </section>
        </>
      )}
    </div>
  );
}

function Profile({ user, busy, run, onUser }: { user: User; busy: boolean; run: Run; onUser: (u: User) => void }) {
  const saveName = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const name = String(new FormData(e.currentTarget).get("display_name") || "");
    run(() => api<User>("/me", { display_name: name }, "PATCH").then(onUser), "显示名称已更新。");
  };
  const savePassword = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget,
      f = new FormData(form);
    if (f.get("new") !== f.get("confirm")) {
      run(() => Promise.reject(new Error("两次输入的新密码不一致。")));
      return;
    }
    run(() => api("/me/password", { current: f.get("current"), new: f.get("new") }), "密码已修改，其他已登录的窗口需要重新登录。").then(
      (ok) => ok && form.reset(),
    );
  };
  return (
    <section className="manage-card settings-section">
      <h2>我的账号</h2>
      <p className="muted">
        用户名：{user.username} · {user.role === "admin" ? "管理员" : "学习者"}
      </p>
      <form className="inline-form" onSubmit={saveName}>
        <label>
          显示名称
          <input name="display_name" defaultValue={user.display_name} maxLength={40} />
        </label>
        <button className="secondary" disabled={busy}>保存</button>
      </form>
      <form className="inline-form" onSubmit={savePassword}>
        <label>
          当前密码
          <input name="current" type="password" required autoComplete="current-password" />
        </label>
        <label>
          新密码
          <input name="new" type="password" required minLength={8} maxLength={128} autoComplete="new-password" />
        </label>
        <label>
          确认新密码
          <input name="confirm" type="password" required minLength={8} maxLength={128} autoComplete="new-password" />
        </label>
        <button className="secondary" disabled={busy}>修改密码</button>
      </form>
    </section>
  );
}
function Provider({ busy, run, onStatus }: { busy: boolean; run: Run; onStatus: () => void }) {
  const [state, setState] = useState<ProviderState>();
  const load = useCallback(() => {
    api<ProviderState>("/settings/provider").then(setState).catch(() => undefined);
  }, []);
  useEffect(load, [load]);
  const save = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget,
      f = new FormData(form);
    const body = { api_key: String(f.get("api_key") || "").trim(), remember: f.get("remember") === "on" };
    run(async () => {
      let next: ProviderState;
      try {
        // DeepSeek checks the key first; a rejected key is never stored.
        next = await api<ProviderState>("/settings/provider", body, "PUT");
      } catch (e) {
        if (!(e instanceof ApiError && e.code === "unverified")) throw e;
        if (!window.confirm(e.message + "\n\n要先保存，等网络恢复后再用“测试当前密钥”确认吗？")) return "未保存密钥。";
        next = await api<ProviderState>("/settings/provider", { ...body, verify: false }, "PUT");
      }
      setState(next);
      form.reset();
      onStatus();
      return next.verified === false
        ? "密钥已保存，但还没有通过 DeepSeek 验证。网络恢复后请点“测试当前密钥”。"
        : "密钥已通过 DeepSeek 验证并保存，所有账号立即可用。";
    });
  };
  const clear = () =>
    window.confirm("清除 DeepSeek 密钥？清除后所有账号都无法生成新的教学内容。") &&
    run(async () => {
      const next = await api<ProviderState>("/settings/provider", undefined, "DELETE");
      setState(next);
      onStatus();
      if (next.notice) throw new Error(next.notice);
    }, "密钥已清除。");
  return (
    <section className="manage-card settings-section">
      <h2>
        <KeyRound size={18} /> DeepSeek API 密钥
      </h2>
      {state ? (
        <p className={state.configured ? "" : "danger"}>
          {state.configured ? `已配置（${SOURCE[state.source || ""] || "已生效"}）· 模型 ${state.model}` : "尚未配置，学习者暂时无法生成讲义和练习。"}
          {state.exhausted && "。上次调用提示额度不足，请到 DeepSeek 官网确认余额。"}
        </p>
      ) : (
        <LoaderCircle className="spin" />
      )}
      <p className="muted">密钥只保存在 Windows 凭据管理器或本次运行的内存中，不会写入学习数据库，页面也不会再显示它。</p>
      {state && (
      <form className="inline-form" onSubmit={save}>
        <label>
          {state.configured ? "更换密钥" : "填写密钥"}
          <input name="api_key" type="password" required minLength={10} maxLength={400} autoComplete="off" spellCheck={false} placeholder="sk-..." />
        </label>
        <label className="checkbox">
          <input name="remember" type="checkbox" defaultChecked={state.remember_supported} disabled={!state.remember_supported} />
          记住密钥{state.remember_supported ? "" : "（此设备不支持）"}
        </label>
        <button className="primary" disabled={busy}>
          {busy ? <LoaderCircle className="spin" size={16} /> : <KeyRound size={16} />} 验证并保存
        </button>
      </form>
      )}
      {state?.configured && (
        <div className="button-row">
          <button className="secondary" disabled={busy} onClick={() => run(() => api("/settings/provider/test", {}), "DeepSeek 已接受当前密钥。")}>
            测试当前密钥
          </button>
          <button className="secondary danger" disabled={busy} onClick={clear}>
            <Trash2 size={16} /> 清除密钥
          </button>
        </div>
      )}
    </section>
  );
}

function Accounts({ me, busy, run }: { me: User; busy: boolean; run: Run }) {
  const [users, setUsers] = useState<User[]>([]),
    [resetting, setResetting] = useState<string>();
  const load = useCallback(() => {
    api<User[]>("/users").then(setUsers).catch(() => undefined);
  }, []);
  useEffect(load, [load]);
  const act = (work: () => Promise<unknown>, done: string) => run(work, done).then((ok) => ok && load());
  const add = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = e.currentTarget,
      f = new FormData(form);
    act(
      () => api("/users", { username: f.get("username"), display_name: f.get("display_name"), password: f.get("password"), role: f.get("role") }),
      "账号已创建，请把用户名和初始密码告诉使用者。",
    ).then(() => form.reset());
  };
  const reset = (e: React.FormEvent<HTMLFormElement>, u: User) => {
    e.preventDefault();
    const password = String(new FormData(e.currentTarget).get("password") || "");
    act(() => api(`/users/${u.id}/password`, { password }), `已重置 ${u.username} 的密码，其原有登录已失效。`).then(() => setResetting(undefined));
  };
  const remove = (u: User) =>
    window.confirm(`删除账号“${u.username}”及其 ${u.course_count || 0} 门课程、错题本和上传资料？此操作无法撤销。`) &&
    act(() => api(`/users/${u.id}`, undefined, "DELETE"), "账号已删除。");
  return (
    <section className="manage-card settings-section">
      <h2>
        <Users size={18} /> 账号管理
      </h2>
      <table className="user-table">
        <thead>
          <tr>
            <th scope="col">用户名</th>
            <th scope="col">显示名称</th>
            <th scope="col">角色</th>
            <th scope="col">课程</th>
            <th scope="col">状态</th>
            <th scope="col"><span className="visually-hidden">操作</span></th>
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id}>
              <td>{u.username}</td>
              <td>{u.display_name}</td>
              <td>{u.role === "admin" ? "管理员" : "学习者"}</td>
              <td>{u.course_count ?? 0}</td>
              <td>{u.disabled ? "已停用" : "正常"}</td>
              <td>
                {u.id === me.id ? (
                  <span className="muted">当前账号</span>
                ) : resetting === u.id ? (
                  <form className="inline-form compact" onSubmit={(e) => reset(e, u)}>
                    <input name="password" type="password" required minLength={8} maxLength={128} aria-label={`${u.username} 的新密码`} autoComplete="new-password" autoFocus />
                    <button className="secondary small" disabled={busy}>确定</button>
                    <button type="button" className="text-button" onClick={() => setResetting(undefined)}>取消</button>
                  </form>
                ) : (
                  <div className="button-row">
                    <button className="text-button" disabled={busy} onClick={() => setResetting(u.id)}>重置密码</button>
                    <button className="text-button" disabled={busy}
                      onClick={() => act(() => api(`/users/${u.id}`, { role: u.role === "admin" ? "learner" : "admin" }, "PATCH"), "角色已更新。")}>
                      {u.role === "admin" ? "设为学习者" : "设为管理员"}
                    </button>
                    <button className="text-button" disabled={busy}
                      onClick={() => act(() => api(`/users/${u.id}`, { disabled: !u.disabled }, "PATCH"), u.disabled ? "账号已启用。" : "账号已停用，其登录已失效。")}>
                      {u.disabled ? "启用" : "停用"}
                    </button>
                    <button className="text-button danger" disabled={busy} onClick={() => remove(u)}>删除</button>
                  </div>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="inline-form" aria-label="添加账号" onSubmit={add}>
        <label>
          用户名
          <input name="username" required minLength={2} maxLength={32} autoComplete="off" />
        </label>
        <label>
          显示名称
          <input name="display_name" maxLength={40} />
        </label>
        <label>
          初始密码
          <input name="password" type="password" required minLength={8} maxLength={128} autoComplete="new-password" />
        </label>
        <label>
          角色
          <select name="role" defaultValue="learner">
            <option value="learner">学习者</option>
            <option value="admin">管理员</option>
          </select>
        </label>
        <button className="primary" disabled={busy}>
          <UserPlus size={16} /> 添加账号
        </button>
      </form>
    </section>
  );
}

function About({ info, admin }: { info?: SystemInfo; admin: boolean }) {
  if (!info) return null;
  const usage = info.usage;
  return (
    <section className="manage-card settings-section">
      <h2>
        <Info size={18} /> 关于与数据
      </h2>
      <p>
        知行 AI 学习工作室 {info.version} · <a href="/api/report" target="_blank" rel="noreferrer">项目汇报</a>
      </p>
      <p className="muted">
        超过 {info.retention_days} 天没有打开、也没有学习记录的课程，会在下次启动时自动删除（连同它的错题和审核记录）。上传的资料和内置教材不会自动删除。需要长期保留的课程请在“学习进度”里导出。
      </p>
      {admin && info.database && (
        <>
          <h3>
            <Database size={16} /> 数据位置与备份
          </h3>
          <p className="muted">所有账号的课程、错题本和资料都存在这个文件里（密钥不在其中）：</p>
          <code className="code-path">{info.database}</code>
          <p className="muted">
            “下载备份”会在程序运行时生成一份完整、一致的数据库副本（含所有账号的学习记录和密码散列，不含 DeepSeek 密钥），请妥善保管。恢复时先退出程序，删除同目录的 learning.sqlite-wal 和 learning.sqlite-shm（如果有），再用备份文件替换上面的 learning.sqlite。忘记管理员密码时，见使用说明里的“重置密码”。
          </p>
          <div className="button-row">
            <a className="secondary small" href="/api/admin/backup" download>
              <Download size={15} /> 下载备份
            </a>
            <a className="secondary small" href="/api/admin/logs" target="_blank" rel="noreferrer">
              <FileWarning size={15} /> 查看错误日志
            </a>
          </div>
          {info.log_file && (
            <p className="muted small">
              错误日志只记录在本机（已去除密钥，不含学习内容），反馈问题时可以附上：<code className="code-path">{info.log_file}</code>
            </p>
          )}
        </>
      )}
      {admin && usage && (
        <p className="muted">
          模型用量（现有课程累计）：{usage.calls} 次调用，输入 {usage.prompt_tokens.toLocaleString()} tokens，输出{" "}
          {usage.completion_tokens.toLocaleString()} tokens，按配置单价估算约 ¥{usage.estimated_cost_cny.toFixed(4)}。这不是 DeepSeek 账单，失败请求和已删除课程未计入。
        </p>
      )}
    </section>
  );
}
