import { useState } from "react";
import { LoaderCircle, LogIn, ShieldCheck } from "lucide-react";
import { api } from "./api";
import type { User } from "./api";

// First run creates the administrator; afterwards only login is offered.
export default function AuthScreen({
  setup,
  onDone,
}: {
  setup: boolean;
  onDone: (user: User) => void;
}) {
  const [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    if (setup && f.get("password") !== f.get("confirm")) {
      setError("两次输入的密码不一致。");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const body = {
        username: String(f.get("username") || "").trim(),
        password: String(f.get("password") || ""),
        ...(setup ? { display_name: String(f.get("display_name") || "") } : {}),
      };
      const r = await api<{ user: User }>(
        setup ? "/auth/setup" : "/auth/login",
        body,
      );
      onDone(r.user);
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="auth-page">
      <section className="auth-card" aria-labelledby="auth-title">
        <div className="brand">
          <span className="brand-symbol">知</span>
          <span>
            知行<span className="brand-sub">AI 学习工作室</span>
          </span>
        </div>
        <h1 id="auth-title">{setup ? "创建管理员账号" : "登录"}</h1>
        <p className="muted">
          {setup
            ? "首次使用请创建管理员。管理员可以设置 DeepSeek 密钥、添加其他学习账号；本机已有的学习记录会归入此账号。"
            : "每个账号的课程、错题本和资料互相独立。忘记密码请联系管理员重置。"}
        </p>
        <form onSubmit={submit}>
          <label>
            用户名
            <input name="username" required autoComplete="username" minLength={2} maxLength={32} autoFocus />
          </label>
          {setup && (
            <label>
              显示名称（可选）
              <input name="display_name" maxLength={40} />
            </label>
          )}
          <label>
            密码
            <input
              name="password"
              type="password"
              required
              minLength={setup ? 8 : 1}
              maxLength={128}
              autoComplete={setup ? "new-password" : "current-password"}
            />
          </label>
          {setup && (
            <label>
              确认密码
              <input name="confirm" type="password" required minLength={8} maxLength={128} autoComplete="new-password" />
            </label>
          )}
          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          <button className="primary full" disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={17} /> : setup ? <ShieldCheck size={17} /> : <LogIn size={17} />}
            {setup ? "创建并进入" : "登录"}
          </button>
        </form>
      </section>
    </main>
  );
}
