import { useCallback, useEffect, useState } from "react";
import { Check, ClipboardCheck, PenLine, Users } from "lucide-react";
import { api, requestId } from "./api";
import type { FeedbackItem, LearnerProgress, Question, TeacherReview } from "./api";
import Markdown from "./Markdown";
import LoadState from "./LoadState";

const KIND: Record<string, string> = {
  grade: "练习评分",
  appeal: "学习者申诉",
  diagnostic: "起点测评",
  assessment: "阶段测验",
  notebook: "错题复习",
  lesson: "讲义",
  assignment: "练习题",
  chat: "追问回答",
  course: "课程草案",
};
const day = (value?: string | null) => (value ? new Date(value).toLocaleString("zh-CN") : "—");
type Graded = { questions?: Question[]; feedback?: { items: FeedbackItem[] } };

// Teacher review channel. AI review stays the default and never blocks learners;
// this page lists the AI-uncertain records so an administrator may confirm or correct them.
export default function TeacherPage({ onChanged }: { onChanged: () => void }) {
  const [tab, setTab] = useState<"reviews" | "progress">("reviews");
  return (
    <div className="manage-page">
      <h1>
        <ClipboardCheck /> 教师审核
      </h1>
      <p className="muted">
        学习过程默认由 AI 自动审核，不会等待教师。这里列出 AI 标记“建议核对”的记录，管理员可以确认或改分；改分后系统会重新计算该学员的掌握进度。
      </p>
      <div className="lesson-tabs">
        <button className={tab === "reviews" ? "selected" : ""} onClick={() => setTab("reviews")}>
          待审核记录
        </button>
        <button className={tab === "progress" ? "selected" : ""} onClick={() => setTab("progress")}>
          学员进度
        </button>
      </div>
      {tab === "reviews" ? <Reviews onChanged={onChanged} /> : <Progress />}
    </div>
  );
}

function Reviews({ onChanged }: { onChanged: () => void }) {
  const [status, setStatus] = useState("open"),
    [items, setItems] = useState<TeacherReview[]>(),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState("");
  const load = useCallback(() => {
    setError("");
    setItems(undefined);
    api<TeacherReview[]>(`/teacher/reviews?status=${status}`)
      .then(setItems)
      .catch((e) => setError(e.message));
  }, [status]);
  useEffect(load, [load]);
  const resolve = async (r: TeacherReview, body: { action: string; reason: string; score?: number; question_id?: string }) => {
    setBusy(true);
    setMessage("");
    try {
      await api(`/reviews/${r.id}/resolve`, { ...body, request_id: requestId() });
      setMessage(body.action === "revise" ? "已改分，学员的掌握进度已重新计算。" : "已确认 AI 审核结果。");
      load();
      onChanged();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };
  return (
    <section>
      <label className="inline-label">
        显示
        <select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="open">待审核</option>
          <option value="resolved">已处理</option>
          <option value="all">全部</option>
        </select>
      </label>
      {message && (
        <p className="form-notice" role="status">
          {message}
        </p>
      )}
      {!items ? (
        <LoadState error={error} onRetry={load} />
      ) : !items.length ? (
        <p>{status === "open" ? "没有待审核的记录。" : "没有记录。"}</p>
      ) : (
        <ul className="manage-list">
          {items.map((r) => (
            <ReviewCard key={r.id} review={r} busy={busy} onResolve={(body) => resolve(r, body)} />
          ))}
        </ul>
      )}
    </section>
  );
}

function ReviewCard({
  review: r,
  busy,
  onResolve,
}: {
  review: TeacherReview;
  busy: boolean;
  onResolve: (body: { action: string; reason: string; score?: number; question_id?: string }) => void;
}) {
  const [reason, setReason] = useState("");
  const graded = (r.content || {}) as Graded;
  const items = r.history_id ? graded.feedback?.items || [] : [];
  const open = r.teacher_status !== "resolved";
  const note = reason.trim() || "教师确认";
  return (
    <li className="manage-card review-card">
      <header>
        <small>
          {r.learner} · {r.course_title}
          {r.unit_title ? " · " + r.unit_title : ""} · {day(r.created_at)}
        </small>
        <span className={"badge " + (open ? "amber" : "")}>{open ? KIND[r.kind] || r.kind : "已处理"}</span>
      </header>
      <p>{r.reason}</p>
      {r.ai_review && <p className="muted">AI 建议：{r.ai_review.advice}</p>}
      {r.teacher_review && (
        <p className="muted">
          处理：{r.teacher_review.action === "revise" ? "改分" : "确认"} · {r.teacher_review.by} · {r.teacher_review.reason}
        </p>
      )}
      {items.map((item) => (
        <GradeItem
          key={item.question_id}
          item={item}
          question={graded.questions?.find((q) => q.id === item.question_id)}
          disabled={busy || !open}
          onScore={(score) => onResolve({ action: "revise", score, question_id: item.question_id, reason: note })}
        />
      ))}
      {!items.length && r.content !== undefined && (
        <details>
          <summary>查看原始记录</summary>
          <pre className="raw-record">{JSON.stringify(r.content, null, 1).slice(0, 6000)}</pre>
        </details>
      )}
      {open && (
        <div className="inline-form">
          <label>
            处理说明
            <input value={reason} maxLength={400} onChange={(e) => setReason(e.target.value)} placeholder="可选，例如：论证完整，评分合理" />
          </label>
          <button className="secondary small" disabled={busy} onClick={() => onResolve({ action: "approve", reason: note })}>
            <Check size={15} /> 确认 AI 结果
          </button>
        </div>
      )}
    </li>
  );
}

function GradeItem({
  item,
  question,
  disabled,
  onScore,
}: {
  item: FeedbackItem & { answer?: string };
  question?: Question & { expected_answer?: string };
  disabled: boolean;
  onScore: (score: number) => void;
}) {
  const [score, setScore] = useState(String(Math.round(item.score * 100)));
  const value = Number(score);
  const valid = score.trim() !== "" && Number.isFinite(value) && value >= 0 && value <= 100;
  return (
    <div className="feedback-item">
      <strong>
        {Math.round(item.score * 100)} 分{item.original_score !== undefined && item.original_score !== item.score ? `（原 ${Math.round(item.original_score * 100)} 分）` : ""}
        {item.ai_uncertain ? " · AI 建议核对" : ""}
      </strong>
      {question && <Markdown text={question.prompt} />}
      <p className="muted">学员作答：{item.answer || "—"}</p>
      {question?.expected_answer && <p className="muted">参考答案：{question.expected_answer}</p>}
      <Markdown text={item.feedback} />
      {item.appeal && (
        <p className="muted">
          申诉理由：{item.appeal.reason}（AI 重新批改：{Math.round(item.appeal.original_score * 100)} → {Math.round(item.appeal.regrade_score * 100)} 分）
        </p>
      )}
      {!disabled && (
        <form
          className="inline-form compact"
          onSubmit={(e) => {
            e.preventDefault();
            if (valid) onScore(value / 100);
          }}
        >
          <label>
            改为
            <input type="number" min={0} max={100} step={1} value={score} onChange={(e) => setScore(e.target.value)} aria-label="新的分数（0–100）" />
          </label>
          <button className="secondary small" disabled={!valid}>
            <PenLine size={15} /> 改分
          </button>
        </form>
      )}
    </div>
  );
}

function Progress() {
  const [rows, setRows] = useState<LearnerProgress[]>(),
    [error, setError] = useState("");
  const load = useCallback(() => {
    setError("");
    api<LearnerProgress[]>("/admin/progress")
      .then(setRows)
      .catch((e) => setError(e.message));
  }, []);
  useEffect(load, [load]);
  if (!rows) return <LoadState error={error} onRetry={load} />;
  return (
    <section>
      <p className="muted">
        <Users size={14} /> 只统计进度和用量，不显示作答内容和对话。得分来自 AI 批改，未经教师确认的不是正式成绩。
      </p>
      <table className="user-table">
        <thead>
          <tr>
            <th scope="col">学员</th>
            <th scope="col">课程</th>
            <th scope="col">已掌握</th>
            <th scope="col">练习次数</th>
            <th scope="col">平均得分</th>
            <th scope="col">待复习错题</th>
            <th scope="col">AI 调用</th>
            <th scope="col">最近学习</th>
          </tr>
        </thead>
        <tbody>
          {rows.flatMap((u) =>
            (u.courses.length ? u.courses : [undefined]).map((c, i) => (
              <tr key={u.user_id + (c?.id || "")}>
                <td>{i === 0 ? `${u.display_name || u.username}${u.disabled ? "（已停用）" : ""}` : ""}</td>
                <td>{c?.title || <span className="muted">还没有课程</span>}</td>
                <td>{c ? `${c.mastered} / ${c.planned_units}` : ""}</td>
                <td>{c?.attempts ?? ""}</td>
                <td>{c ? (c.average_score === null ? "—" : Math.round(c.average_score * 100)) : ""}</td>
                <td>{c ? `${c.notebook_due} / ${c.notebook_total}` : ""}</td>
                <td>{c ? `${c.ai_calls} 次` : ""}</td>
                <td>{c ? day(c.last_activity) : ""}</td>
              </tr>
            )),
          )}
        </tbody>
      </table>
    </section>
  );
}
