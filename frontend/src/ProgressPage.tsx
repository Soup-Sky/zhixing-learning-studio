import { useCallback, useEffect, useState } from "react";
import { ArrowRight, BarChart3, Download, Pencil, Trash2 } from "lucide-react";
import { api } from "./api";
import type { CourseSummary, NotebookItem } from "./api";
import { courseStatusLabel, masteryPercent, reviewGroups } from "./plan";
import LoadState from "./LoadState";

const date = (value?: string) => (value ? new Date(value).toLocaleDateString("zh-CN") : "—");

export default function ProgressPage({
  onOpen,
  onReview,
  onChanged,
  onError,
}: {
  onOpen: (id: string) => void;
  onReview: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [courses, setCourses] = useState<CourseSummary[]>(),
    [notes, setNotes] = useState<NotebookItem[]>([]),
    [loadError, setLoadError] = useState("");
  const load = useCallback(() => {
    setLoadError("");
    Promise.all([api<CourseSummary[]>("/courses"), api<NotebookItem[]>("/notebook")])
      .then(([c, n]) => {
        setCourses(c);
        setNotes(n);
      })
      .catch((e) => setLoadError(e.message));
  }, []);
  useEffect(load, [load]);
  const rename = async (c: CourseSummary) => {
    const title = window.prompt("新的课程名称", c.title)?.trim();
    if (!title || title === c.title) return;
    try {
      await api(`/courses/${c.id}`, { title }, "PATCH");
      load();
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : "重命名失败");
    }
  };
  const remove = async (c: CourseSummary) => {
    if (!window.confirm(`删除“${c.title}”及其讲义、作答记录和错题本？此操作无法撤销，建议先导出。`)) return;
    try {
      await api(`/courses/${c.id}`, undefined, "DELETE");
      load();
      onChanged();
    } catch (e) {
      onError(e instanceof Error ? e.message : "删除失败");
    }
  };
  if (!courses) return <LoadState error={loadError} onRetry={load} />;
  const due = reviewGroups(notes).due;
  const titles = Object.fromEntries(courses.map((c) => [c.id, c.title]));
  return (
    <div className="manage-page">
      <h1>
        <BarChart3 /> 学习进度
      </h1>
      <p className="muted">掌握度来自练习评分与 AI 审核，不代表经过教师或真人测评确认。</p>
      {!courses.length && <p>还没有学习主题。</p>}
      <div className="progress-list">
        {courses.map((c) => {
          const p = c.progress;
          const percent = p ? masteryPercent(p.mastered, p.planned_units) : 0;
          return (
            <article className="manage-card" key={c.id}>
              <header>
                <h2>{c.title}</h2>
                <span className="badge">{courseStatusLabel(c.status)}</span>
              </header>
              <div
                className="progress-bar"
                role="progressbar"
                aria-label={`${c.title} 掌握进度`}
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={percent}
              >
                <span style={{ width: percent + "%" }} />
              </div>
              {p && (
                <dl className="progress-facts">
                  <div><dt>已掌握</dt><dd>{p.mastered} / {p.planned_units} 单元</dd></div>
                  <div><dt>学习中</dt><dd>{p.learning}</dd></div>
                  <div><dt>练习次数</dt><dd>{p.attempts}</dd></div>
                  <div><dt>平均得分</dt><dd>{p.average_score === null ? "—" : Math.round(p.average_score * 100)}</dd></div>
                  <div><dt>错题待复习</dt><dd>{p.notebook_due} / {p.notebook_total}</dd></div>
                  <div><dt>最近学习</dt><dd>{date(p.last_activity)}</dd></div>
                </dl>
              )}
              <footer>
                <button className="primary small" onClick={() => onOpen(c.id)}>
                  继续学习 <ArrowRight size={15} />
                </button>
                <button className="secondary small" onClick={() => rename(c)}>
                  <Pencil size={15} /> 重命名
                </button>
                <a className="secondary small" href={`/api/courses/${c.id}/export`} download>
                  <Download size={15} /> 导出
                </a>
                <button className="secondary small danger" onClick={() => remove(c)}>
                  <Trash2 size={15} /> 删除
                </button>
              </footer>
            </article>
          );
        })}
      </div>
      {due.length > 0 && (
        <section>
          <h2>今天该复习的错题</h2>
          <ul className="due-list">
            {due.map((n) => (
              <li key={n.id}>
                {titles[n.course_id] || "课程"} · {n.question.slice(0, 80)}
              </li>
            ))}
          </ul>
          <button className="primary small" onClick={onReview}>
            去错题本复习 <ArrowRight size={15} />
          </button>
        </section>
      )}
    </div>
  );
}
