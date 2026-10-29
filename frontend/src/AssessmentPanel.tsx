import { useEffect, useRef, useState } from "react";
import { LoaderCircle } from "lucide-react";
import { api, requestId, waitForTask } from "./api";
import type { AssessmentRecord, Course, Feedback, Question } from "./api";
import Questions from "./Questions";
import { FeedbackView } from "./LearningWorkspace";
import LoadState from "./LoadState";

const KINDS = { pre: "前测（学习前）", post: "后测（学完后）", delayed: "延迟测（隔一段时间后）" } as const;
type Kind = keyof typeof KINDS;

// Fixed question sets from the built-in bank, separate from practice, for before/after comparison.
export default function AssessmentPanel({ course, onError }: { course: Course; onError: (message: string) => void }) {
  const [kind, setKind] = useState<Kind>("pre"),
    [questions, setQuestions] = useState<Question[]>(),
    [busy, setBusy] = useState(false),
    [progress, setProgress] = useState(""),
    [result, setResult] = useState<Feedback>(),
    [records, setRecords] = useState<AssessmentRecord[]>(course.assessments || []),
    [attempt, setAttempt] = useState(0),
    [loadError, setLoadError] = useState(""),
    [reload, setReload] = useState(0);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    let active = true;
    setQuestions(undefined);
    setResult(undefined);
    setLoadError("");
    api<{ questions: Question[] }>(`/courses/${course.id}/assessment?kind=${kind}`)
      .then((r) => active && setQuestions(r.questions))
      .catch((e) => active && setLoadError(e.message));
    return () => {
      active = false;
    };
  }, [course.id, kind, reload]);
  const submit = async (answers: { question_id: string; answer: string }[]) => {
    setBusy(true);
    setProgress("已提交，等待批改");
    try {
      const { task_id } = await api<{ task_id: string }>(`/courses/${course.id}/assessment`, {
        kind,
        answers,
        request_id: requestId(),
      });
      const task = await waitForTask(task_id, (t) => t.progress.length && setProgress(t.progress.at(-1)!), () => alive.current);
      if (!alive.current) return;
      if (task.status !== "completed") throw new Error(task.error || "批改未完成");
      const feedback = task.result as Feedback;
      setResult(feedback);
      setRecords((r) => [...r, { id: task_id, kind, at: new Date().toISOString(), result: feedback }]);
      setAttempt((n) => n + 1);
    } catch (e) {
      if (alive.current) onError(e instanceof Error ? e.message : "批改未完成");
    } finally {
      if (alive.current) {
        setBusy(false);
        setProgress("");
      }
    }
  };
  return (
    <section className="assessment-panel">
      <p className="muted">
        固定题目、不计入练习，用来比较学习前后的变化。分数由 SymPy 核验和 AI 按量规批改得出，未经教师确认，不能当作正式成绩。
      </p>
      <label>
        测验类型
        <select value={kind} disabled={busy} onChange={(e) => setKind(e.target.value as Kind)}>
          {Object.entries(KINDS).map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </select>
      </label>
      {records.length > 0 && (
        <ul className="assessment-history">
          {records.map((r) => (
            <li key={r.id}>
              {KINDS[r.kind]} · {new Date(r.at).toLocaleDateString("zh-CN")} · {Math.round(r.result.score * 100)} 分
            </li>
          ))}
        </ul>
      )}
      {result && <FeedbackView feedback={result} title="测验结果" />}
      {busy && progress && (
        <p role="status">
          <LoaderCircle className="spin" size={15} /> {progress}
        </p>
      )}
      {questions ? (
        <Questions
          key={kind + attempt}
          questions={questions}
          topic={course.topic}
          busy={busy}
          label="提交测验"
          submit={submit}
        />
      ) : (
        <LoadState error={loadError} onRetry={() => setReload((n) => n + 1)} />
      )}
    </section>
  );
}
