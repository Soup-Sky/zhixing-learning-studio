import { useCallback, useEffect, useState } from "react";
import { FileText, Library, Link, LoaderCircle, Trash2, Upload } from "lucide-react";
import { api } from "./api";
import type { SourceItem } from "./api";
import LoadState from "./LoadState";

export default function SourcesPage({ onError }: { onError: (message: string) => void }) {
  const [sources, setSources] = useState<SourceItem[]>(),
    [busy, setBusy] = useState(false),
    [notice, setNotice] = useState(""),
    [loadError, setLoadError] = useState("");
  const load = useCallback(() => {
    setLoadError("");
    api<SourceItem[]>("/sources").then(setSources).catch((e) => setLoadError(e.message));
  }, []);
  useEffect(load, [load]);
  const run = async (work: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setNotice("");
    try {
      await work();
      setNotice(done);
      load();
    } catch (e) {
      onError(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };
  const upload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    if (!file) return;
    const form = new FormData();
    form.append("file", file);
    run(() => api("/sources/upload", form), `已添加“${file.name}”。`);
  };
  const addUrl = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const input = e.currentTarget.elements.namedItem("url") as HTMLInputElement;
    const url = input.value.trim();
    if (!url) return;
    run(() => api("/sources/url", { url }), "已抓取网页正文。").then(() => (input.value = ""));
  };
  const remove = (s: SourceItem) => {
    const used = s.used_by?.length ? `它被 ${s.used_by.length} 门课程引用，删除后这些课程今后不再使用它。` : "";
    if (window.confirm(`删除资料“${s.title}”？${used}`))
      run(() => api(`/sources/${s.id}`, undefined, "DELETE"), "资料已删除。");
  };
  return (
    <div className="manage-page">
      <h1>
        <Library /> 学习资料
      </h1>
      <p className="muted">
        上传的文件和网址只对当前账号可见。新建学习主题时可以选择要使用的资料。内置教材为所有账号共享。
      </p>
      <div className="source-tools">
        <label className="secondary upload-button">
          <Upload size={16} /> 上传资料（PDF、Word、TXT、MD，4MB 以内）
          <input type="file" accept=".pdf,.docx,.txt,.md" onChange={upload} disabled={busy} />
        </label>
        <form onSubmit={addUrl}>
          <input name="url" type="url" placeholder="https://..." aria-label="资料网址" disabled={busy} />
          <button className="secondary" disabled={busy}>
            {busy ? <LoaderCircle className="spin" size={16} /> : <Link size={16} />} 添加网址
          </button>
        </form>
      </div>
      {notice && <p className="form-notice" role="status">{notice}</p>}
      {!sources ? (
        <LoadState error={loadError} onRetry={load} />
      ) : !sources.length ? (
        <p>还没有资料。</p>
      ) : (
        <ul className="manage-list">
          {sources.map((s) => (
            <li className="manage-card" key={s.id}>
              <FileText size={18} />
              <div>
                <strong>{s.url ? <a href={s.url} target="_blank" rel="noreferrer">{s.title}</a> : s.title}</strong>
                <small>
                  {s.shared ? "内置共享" : "我的资料"}
                  {s.license ? " · " + s.license.slice(0, 60) : ""}
                  {s.used_by?.length ? " · 用于：" + s.used_by.map((c) => c.title).join("、") : " · 未被课程使用"}
                </small>
                {s.text && <p className="muted">{s.text.slice(0, 160)}</p>}
              </div>
              {!s.shared && (
                <button className="icon-button" aria-label={`删除 ${s.title}`} onClick={() => remove(s)} disabled={busy}>
                  <Trash2 size={16} />
                </button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
