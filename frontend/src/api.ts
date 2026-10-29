export type Question = {
  id: string;
  prompt: string;
  kind: string;
  unit_id?: string;
  rubric?: { criterion: string; points: number }[];
  hints?: string[];
};
export type Unit = {
  id: string;
  title: string;
  prerequisites: string[];
  objectives: string[];
  estimated_minutes?: number;
  review_status?: string;
  content?: string;
};
export type Source = {
  id: string;
  title: string;
  url?: string;
  locator?: string;
  license?: string;
  review_status?: string;
  text?: string;
  version?: string;
  record_ids?: string[];
  relevance_note?: string;
};
export type AIReview = {
  verdict: "accepted" | "revise" | "uncertain" | string;
  advice: string;
  issues: string[];
  confidence?: number;
};
export type Feedback = {
  score: number;
  needs_human_review?: boolean;
  ai_uncertain?: boolean;
  decision: string;
  explanation?: string;
  next_unit_id?: string;
  ai_review?: AIReview;
  items: FeedbackItem[];
};
export type TeacherDecision = { action: string; reason: string; by?: string; at: string };
export type Appeal = {
  question_id: string;
  reason: string;
  original_score: number;
  regrade_score: number;
  feedback: string;
  at: string;
};
export type FeedbackItem = {
  question_id: string;
  score: number;
  feedback: string;
  solution?: string;
  expected_answer?: string;
  error_type?: string;
  evidence?: unknown;
  ai_review?: AIReview;
  ai_uncertain?: boolean;
  original_score?: number;
  appeal?: Appeal;
  teacher_review?: TeacherDecision;
};
export type Message = {
  role: string;
  content: string;
  unit_id?: string;
  selected_text?: string;
  needs_human_review?: boolean;
  ai_review?: AIReview;
};
export type Workspace = {
  unit: Unit;
  lesson?: Course["lesson"];
  assignment?: {
    id: string;
    unit_id?: string;
    submitted?: boolean;
    questions: Question[];
  };
  last_feedback?: Feedback;
  last_history_id?: string;
  history: { assignment_id: string }[];
  messages: Message[];
  next_unit_id?: string;
  recommended_unit_id?: string;
  prerequisites: unknown[];
};
export type Course = {
  id: string;
  title: string;
  topic: string;
  status: string;
  current_unit_id?: string;
  recommended_unit_id?: string;
  units: Unit[];
  profile?: { goal?: string; hours_per_week?: number };
  mastery?: Record<
    string,
    | number
    | {
        score?: number;
        mastery?: number;
        status?: string;
        failures?: number;
        evidence?: unknown;
        ai_confidence?: string;
        ai_advice?: string;
      }
  >;
  diagnostic?: { questions: Question[]; summary?: string };
  clarifications?: string[];
  retrieval_notes?: string[];
  diagnostic_result?: unknown;
  plan?: {
    unit_order: string[];
    weekly_hours: number;
    goal: string;
    reason: string;
    sessions: { unit_id: string; minutes: number; focus: string }[];
  };
  lesson?: {
    title: string;
    body: string;
    examples: { question: string; solution: string }[];
    misconceptions: string[];
    citations: string[];
    needs_human_review: boolean;
    plot?: {
      expression: string;
      x_min: number;
      x_max: number;
      points?: { x: number; y: number }[];
    };
    ai_review?: AIReview;
  };
  assignment?: { id: string; questions: Question[] };
  last_feedback?: Feedback;
  sources?: Source[];
  trace?: unknown[];
  history?: { assignment_id: string }[];
  builtin?: boolean;
  assessments?: AssessmentRecord[];
};
export type Task = {
  id: string;
  action?: string;
  course_id?: string;
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  progress: string[];
  result?: unknown;
  error?: string;
  created_at?: string;
  started_at?: string;
  finished_at?: string;
};
export const taskDone = (t: Task) => t.status === "completed" || t.status === "failed" || t.status === "cancelled";
export type Review = {
  id: string;
  course_id: string;
  kind: string;
  reason: string;
  status: string;
  content?: unknown;
  created_at: string;
  review_mode?: "ai" | string;
  ai_review?: AIReview;
  teacher_status?: "open" | "resolved" | "none";
  teacher_review?: TeacherDecision & { question_id?: string };
  history_id?: string;
  question_id?: string;
};
// Teacher review channel: administrator view across all accounts.
export type TeacherReview = Review & {
  course_title?: string;
  unit_title?: string | null;
  learner: string;
};
export type LearnerProgress = {
  user_id: string;
  username: string;
  display_name?: string;
  role: string;
  disabled: boolean;
  last_activity: string | null;
  courses: (CourseProgress & { id: string; title: string; status: string; ai_calls: number; tokens: number })[];
};
export type Note = {
  id: string;
  unit_id: string;
  question: string;
  answer: string;
  feedback: unknown;
  next_due?: string;
  stage?: number;
  last_result?: Feedback;
};
export type Status = {
  configured: boolean;
  providers: { name: string; model: string; configured: boolean }[];
  version: string;
  retention_days: number;
  needs_setup?: boolean;
};
export type User = {
  id: string;
  username: string;
  display_name: string;
  role: "admin" | "learner";
  disabled: boolean;
  created_at: string;
  course_count?: number;
};
export type AuthState = { needs_setup: boolean; user: User | null };
export type CourseProgress = {
  planned_units: number;
  mastered: number;
  learning: number;
  attempts: number;
  average_score: number | null;
  last_activity: string;
  notebook_total: number;
  notebook_due: number;
};
export type CourseSummary = Course & { progress?: CourseProgress };
export type SourceItem = Source & {
  owner_id?: string | null;
  shared?: boolean;
  used_by?: { id: string; title: string }[];
};
export type ProviderState = {
  configured: boolean;
  source: "env" | "vault" | "session" | null;
  remember_supported: boolean;
  model: string;
  exhausted: boolean;
  notice?: string;
  verified?: boolean;
};
export type NotebookItem = Omit<Note, "feedback"> & {
  course_id: string;
  feedback?: string;
  due_dates?: string[];
  created_at?: string;
};
export type SystemInfo = {
  version: string;
  retention_days: number;
  can_shutdown: boolean;
  database?: string;
  log_file?: string | null;
  usage?: {
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    estimated_cost_cny: number;
  };
};
export type AssessmentRecord = {
  id: string;
  kind: "pre" | "post" | "delayed";
  at: string;
  result: Feedback;
};
// Any 401 from a protected endpoint returns the whole app to the login screen.
export const UNAUTHORIZED = "zhixing-unauthorized";
export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public code?: string,
  ) {
    super(message);
  }
}
export async function api<T>(
  path: string,
  body?: unknown,
  method?: string,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch("/api" + path, {
      method: method || (body === undefined ? "GET" : "POST"),
      headers:
        body instanceof FormData
          ? undefined
          : { "Content-Type": "application/json" },
      body:
        body === undefined
          ? undefined
          : body instanceof FormData
            ? body
            : JSON.stringify(body),
    });
  } catch {
    throw new Error(
      "暂时无法连接学习服务。请检查本地服务是否已启动，然后重试。",
    );
  }
  if (response.status === 401 && !path.startsWith("/auth/"))
    window.dispatchEvent(new Event(UNAUTHORIZED));
  if (!response.ok) {
    let detail = "请求未完成",
      code: string | undefined;
    try {
      const result = await response.json();
      code = typeof result.code === "string" ? result.code : undefined;
      detail =
        typeof result.detail === "string"
          ? result.detail
          : Array.isArray(result.detail)
            ? "填写内容不符合要求：" +
              result.detail
                .map((e: { loc?: unknown[] }) => (e.loc || []).slice(-1).join(""))
                .join("、")
            : JSON.stringify(result.detail || result.error || result);
    } catch {
      detail = response.statusText;
    }
    throw new ApiError(`${detail}（${response.status}）`, response.status, code);
  }
  return response.json();
}
export const requestId = () => crypto.randomUUID();
// Polls a background task until it finishes; alive() lets an unmounted page stop early.
export async function waitForTask(
  id: string,
  onProgress?: (task: Task) => void,
  alive: () => boolean = () => true,
): Promise<Task> {
  // The service stops a task after 20 minutes; this only guards against a stuck page.
  const deadline = Date.now() + 25 * 60 * 1000;
  for (;;) {
    if (Date.now() > deadline) throw new Error("等待超时：任务长时间没有结束，请刷新页面查看结果。");
    const task = await api<Task>(`/tasks/${id}`);
    if (!alive()) return task;
    onProgress?.(task);
    if (taskDone(task)) return task;
    await new Promise((resolve) => setTimeout(resolve, 900));
  }
}
export const cancelTask = (id: string) => api<{ ok: boolean; status: string }>(`/tasks/${id}`, undefined, "DELETE");
