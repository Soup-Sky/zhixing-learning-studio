import { useEffect, useState } from "react";
import { LoaderCircle, Plus, X } from "lucide-react";
import { api } from "./api";
import type { SourceItem } from "./api";

export type CourseDraft = Record<string, unknown>;

// The draft is kept by the parent, so a failed creation reopens with what the learner typed.
export default function NewCourse({
  busy,
  draft,
  onClose,
  onSubmit,
}: {
  busy: boolean;
  draft?: CourseDraft;
  onClose: () => void;
  onSubmit: (data: CourseDraft) => void;
}) {
  const [sources, setSources] = useState<SourceItem[]>([]);
  useEffect(() => {
    api<SourceItem[]>("/sources")
      .then((list) => setSources(list.filter((s) => !s.shared)))
      .catch(() => undefined);
  }, []);
  const value = (key: string, fallback = "") => String(draft?.[key] ?? fallback);
  const chosen = new Set((draft?.source_ids as string[] | undefined) || []);
  const submit = (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    onSubmit({
      topic: String(f.get("topic") || "").trim(),
      background: f.get("background"),
      goal: f.get("goal"),
      hours_per_week: Number(f.get("hours")),
      minutes_per_session: Number(f.get("minutes")),
      preference: f.get("preference"),
      search_web: f.get("web") === "on",
      source_ids: f.getAll("source_ids"),
    });
  };
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <section className="modal" role="dialog" aria-modal="true" aria-labelledby="new-course-title" onClick={(e) => e.stopPropagation()}>
        <button className="icon-button modal-close" aria-label="关闭" onClick={onClose}>
          <X />
        </button>
        <h2 id="new-course-title">开始新的学习主题</h2>
        <form onSubmit={submit}>
          <label>
            学习主题
            <input name="topic" required maxLength={200} defaultValue={value("topic")} placeholder="例如：微积分、统计学、编程" />
          </label>
          <label>
            目前基础
            <textarea name="background" rows={3} required maxLength={2000} defaultValue={value("background")} />
          </label>
          <label>
            学习目标
            <textarea name="goal" rows={2} required maxLength={2000} defaultValue={value("goal")} />
          </label>
          <div className="form-grid">
            <label>
              每周小时
              <input name="hours" type="number" inputMode="decimal" min="0.5" max="100" step="any" required defaultValue={value("hours_per_week", "3")} />
            </label>
            <label>
              每次分钟
              <input name="minutes" type="number" min="5" max="240" step="5" required defaultValue={value("minutes_per_session", "30")} />
            </label>
          </div>
          <label>
            学习方式
            <select name="preference" defaultValue={value("preference", "examples")}>
              <option value="examples">例子优先</option>
              <option value="theory">原理优先</option>
              <option value="step_by_step">逐步练习</option>
            </select>
          </label>
          <label className="checkbox">
            <input type="checkbox" name="web" defaultChecked={draft ? draft.search_web !== false : true} />
            允许检索公开资料
          </label>
          {sources.length > 0 && (
            <fieldset className="source-picker">
              <legend>使用我的资料（可选）</legend>
              {sources.map((s) => (
                <label className="checkbox" key={s.id}>
                  <input type="checkbox" name="source_ids" value={s.id} defaultChecked={chosen.has(s.id)} />
                  {s.title}
                </label>
              ))}
            </fieldset>
          )}
          <button className="primary full" disabled={busy}>
            {busy ? <LoaderCircle className="spin" /> : <Plus />} 创建学习路径
          </button>
        </form>
      </section>
    </div>
  );
}
