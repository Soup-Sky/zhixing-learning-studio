import { useEffect, useState } from "react";
import { AlertCircle, ArrowRight, Check, LoaderCircle, X } from "lucide-react";
import type { Task } from "./api";

const clock = (seconds: number) => `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;

// Seconds since the task was accepted; ticks only while it is still running.
function useElapsed(task?: Task, running = false) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    if (!running) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [running]);
  const start = task?.created_at ? Date.parse(task.created_at) : NaN;
  const end = task?.finished_at ? Date.parse(task.finished_at) : now;
  return Number.isFinite(start) ? Math.max(0, Math.round((end - start) / 1000)) : undefined;
}

export default function OperationFeedback({
  busy,
  task,
  error,
  notice,
  onResult,
  onCancel,
}: {
  busy: boolean;
  task?: Task;
  error: string;
  notice: string;
  onResult?: () => void;
  onCancel?: () => void;
}) {
  const progress = task?.progress?.at(-1);
  const [dismissed, setDismissed] = useState(false);
  const elapsed = useElapsed(task, busy);
  // A finished notice used to sit over the lesson text until the next action.
  useEffect(() => {
    setDismissed(false);
    if (busy || error) return;
    const timer = setTimeout(() => setDismissed(true), 8000);
    return () => clearTimeout(timer);
  }, [busy, error, notice, task?.status]);
  if (dismissed) return null;
  if (!busy && !task && !error && !notice) return null;
  const state = error ? "failure" : notice || task?.status === "completed" ? "success" : "";
  return (
    <aside className={"operation-feedback " + state} role={error ? "alert" : "status"}>
      {error ? <AlertCircle size={18} /> : busy ? <LoaderCircle className="spin" size={18} /> : <Check size={18} />}
      <div>
        <strong>{error ? "操作未完成" : busy ? "正在处理" : notice || "操作完成"}</strong>
        {progress && <p>{progress}</p>}
        {busy && elapsed !== undefined && (
          <p className="muted small">
            已用时 {clock(elapsed)}
            {elapsed > 90 ? " · 生成讲义和练习通常需要 1–3 分钟" : ""}
          </p>
        )}
        {error && <p>{error}</p>}
        {notice && <p>{notice}</p>}
        {onResult && !busy && !error && (
          <button className="text-button" onClick={onResult}>
            查看结果 <ArrowRight size={14} />
          </button>
        )}
        {busy && onCancel && task && (
          <button className="text-button" onClick={onCancel}>
            取消任务
          </button>
        )}
      </div>
      {!busy && (
        <button className="icon-button" aria-label="关闭提示" onClick={() => setDismissed(true)}>
          <X size={15} />
        </button>
      )}
    </aside>
  );
}
