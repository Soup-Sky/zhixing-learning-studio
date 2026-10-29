import { useCallback, useEffect, useRef, useState } from "react";
import { api, cancelTask, requestId, taskDone } from "./api";
import type { Task } from "./api";

export type TaskResult = { course_id?: string; unit_id?: string; action?: string };

// One background task at a time for the studio: start, poll, cancel.
// onFinished runs once per task with the final record, whatever its outcome.
export default function useTaskRunner(onFinished: (task: Task) => void | Promise<void>) {
  const [task, setTask] = useState<Task>(),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const finished = useRef(onFinished);
  finished.current = onFinished;
  const start = useCallback(
    // Resolves false when the request was refused, so callers can keep their form open.
    async (url: string, body: Record<string, unknown>) => {
      if (busy) return false;
      setBusy(true);
      setError("");
      setTask(undefined);
      try {
        const r = await api<{ task_id: string }>(url, { ...body, request_id: requestId() });
        setTask({ id: r.task_id, status: "queued", progress: [], created_at: new Date().toISOString() });
        return true;
      } catch (e) {
        setError(e instanceof Error ? e.message : "请求未完成");
        setBusy(false);
        return false;
      }
    },
    [busy],
  );
  useEffect(() => {
    if (!task) return;
    let stop = false,
      timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api<Task>(`/tasks/${task.id}`);
        if (stop) return;
        setTask(next);
        if (!taskDone(next)) {
          timer = setTimeout(poll, 900);
          return;
        }
        if (next.status === "failed") setError(next.error || "任务未完成");
        await finished.current(next);
        setBusy(false);
      } catch (e) {
        if (!stop) {
          setBusy(false);
          setError(e instanceof Error ? e.message : "任务状态读取失败");
        }
      }
    };
    poll();
    return () => {
      stop = true;
      clearTimeout(timer);
    };
  }, [task?.id]);
  const cancel = useCallback(() => {
    if (task && !taskDone(task)) cancelTask(task.id).catch((e) => setError(e.message));
  }, [task]);
  return { task, busy, error, setError, start, cancel };
}
