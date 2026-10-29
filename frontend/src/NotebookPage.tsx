import { useCallback, useEffect, useRef, useState } from "react";
import { CalendarClock, LoaderCircle, NotebookPen, RotateCcw, Send } from "lucide-react";
import { api, requestId, waitForTask } from "./api";
import type { Course, Feedback, NotebookItem } from "./api";
import Markdown from "./Markdown";
import SymbolInput from "./SymbolInput";
import { FeedbackView } from "./LearningWorkspace";
import { reviewGroups } from "./plan";
import LoadState from "./LoadState";

const day = (value?: string) => (value ? new Date(value).toLocaleDateString("zh-CN") : "");

export default function NotebookPage({
  courses,
  onChanged,
  onError,
}: {
  courses: Course[];
  onChanged: () => void;
  onError: (message: string) => void;
}) {
  const [items, setItems] = useState<NotebookItem[]>(),
    [answering, setAnswering] = useState<string>(),
    [answer, setAnswer] = useState(""),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(""),
    [results, setResults] = useState<Record<string, Feedback>>({}),
    [loadError, setLoadError] = useState("");
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  const load = useCallback(() => {
    setLoadError("");
    api<NotebookItem[]>("/notebook").then(setItems).catch((e) => setLoadError(e.message));
  }, []);
  useEffect(load, [load]);
  const submit = async (item: NotebookItem) => {
    if (busy || !answer.trim()) return;
    setBusy(true);
    setProgress("已提交，等待 AI 批改");
    try {
      const { task_id } = await api<{ task_id: string }>(
        `/courses/${item.course_id}/notebook/${item.id}/review`,
        { answer: answer.trim(), request_id: requestId() },
      );
      const task = await waitForTask(task_id, (t) => t.progress.length && setProgress(t.progress.at(-1)!), () => alive.current);
      if (!alive.current) return;
      if (task.status !== "completed") throw new Error(task.error || "批改未完成");
      setResults((r) => ({ ...r, [item.id]: task.result as Feedback }));
      setAnswering(undefined);
      setAnswer("");
      load();
      onChanged();
    } catch (e) {
      if (alive.current) onError(e instanceof Error ? e.message : "批改未完成");
    } finally {
      if (alive.current) {
        setBusy(false);
        setProgress("");
      }
    }
  };
  if (!items) return <LoadState error={loadError} onRetry={load} />;
  const byId = Object.fromEntries(courses.map((c) => [c.id, c]));
  const groups = reviewGroups(items);
  const card = (item: NotebookItem) => {
    const course = byId[item.course_id];
    const unit = course?.units.find((u) => u.id === item.unit_id);
    const open = answering === item.id;
    return (
      <li className="manage-card note-item" key={item.id}>
        <header>
          <small>
            {course?.title || "课程"}
            {unit ? " · " + unit.title : ""}
          </small>
          <span className="badge">
            {item.next_due ? `第 ${(item.stage ?? 0) + 1} 轮复习` : "已掌握"}
          </span>
        </header>
        <Markdown text={item.question} />
        <details>
          <summary>上次的作答与反馈</summary>
          <p className="muted">我的答案：{item.answer}</p>
          {item.feedback && <Markdown text={item.feedback} />}
        </details>
        {results[item.id] && <FeedbackView feedback={results[item.id]} title="复习结果" />}
        {open ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              submit(item);
            }}
          >
            <label className="answer-label" htmlFor={"note-" + item.id}>
              重新作答
            </label>
            <SymbolInput
              id={"note-" + item.id}
              topic={course?.topic}
              rows={3}
              required
              disabled={busy}
              value={answer}
              onChange={setAnswer}
              placeholder="写下推导过程或答案"
            />
            <div className="button-row">
              <button className="primary small" disabled={busy || !answer.trim()}>
                {busy ? <LoaderCircle className="spin" size={15} /> : <Send size={15} />} 提交批改
              </button>
              <button type="button" className="text-button" disabled={busy} onClick={() => setAnswering(undefined)}>
                取消
              </button>
              {busy && progress && <span className="muted" role="status">{progress}</span>}
            </div>
          </form>
        ) : (
          <div className="button-row">
            <button
              className="secondary small"
              disabled={busy}
              onClick={() => {
                setAnswering(item.id);
                setAnswer("");
              }}
            >
              <RotateCcw size={15} /> 重新作答
            </button>
            {item.next_due && (
              <span className="muted">
                <CalendarClock size={14} /> 计划复习：{day(item.next_due)}
              </span>
            )}
          </div>
        )}
      </li>
    );
  };
  const section = (title: string, list: NotebookItem[]) =>
    list.length > 0 && (
      <section>
        <h2>
          {title} <small className="muted">{list.length}</small>
        </h2>
        <ul className="manage-list">{list.map(card)}</ul>
      </section>
    );
  return (
    <div className="manage-page">
      <h1>
        <NotebookPen /> 错题本
      </h1>
      <p className="muted">
        练习中得分低于 80% 的题会自动收进来。每次答对后，分别隔 1、3、7 天再复习一次（从这次复习算起）；连续答对 3 次视为掌握，答错则明天再练。批改由 AI 完成，未经教师确认。
      </p>
      {!items.length && <p>还没有错题。练习中答错的题会出现在这里。</p>}
      {section("今天该复习", groups.due)}
      {section("之后复习", groups.later)}
      {section("已掌握", groups.done)}
    </div>
  );
}
