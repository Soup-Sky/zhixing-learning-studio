import { useCallback, useEffect, useRef, useState } from "react";
import { ArrowRight, BarChart3, BookOpen, ClipboardCheck, Compass, Library, LoaderCircle, LogOut, NotebookPen, Plus, Settings } from "lucide-react";
import { api, UNAUTHORIZED } from "./api";
import type { AuthState, Course, CourseSummary, Status, Task, User } from "./api";
import LearningWorkspace from "./LearningWorkspace";
import type { ResultTarget } from "./LearningWorkspace";
import SelectionAssistant from "./SelectionAssistant";
import AuthScreen from "./AuthScreens";
import ProgressPage from "./ProgressPage";
import SourcesPage from "./SourcesPage";
import SettingsPage from "./SettingsPage";
import NotebookPage from "./NotebookPage";
import TeacherPage from "./TeacherPage";
import OperationFeedback from "./OperationFeedback";
import NewCourse from "./NewCourse";
import type { CourseDraft } from "./NewCourse";
import useTaskRunner from "./useTaskRunner";
import type { TaskResult } from "./useTaskRunner";
import { courseStatusLabel } from "./plan";

type View = "learn" | "progress" | "notebook" | "sources" | "teacher" | "settings";
// Tasks whose result belongs to a tab of the learning page; chat answers stay in the assistant drawer.
const JUMPS = new Set(["create", "clarify", "diagnostic", "lesson", "answers", "appeal"]);

export default function AppOpen() {
  const [auth, setAuth] = useState<AuthState>(),
    [error, setError] = useState("");
  const check = useCallback(() => api<AuthState>("/auth/state").then(setAuth).catch((e) => setError(e.message)), []);
  useEffect(() => {
    check();
    const expired = () => setAuth((a) => (a && a.user ? { ...a, user: null } : a));
    window.addEventListener(UNAUTHORIZED, expired);
    return () => window.removeEventListener(UNAUTHORIZED, expired);
  }, [check]);
  if (!auth)
    return (
      <main className="auth-page">
        {error ? (
          <p className="form-error" role="alert">
            {error}
          </p>
        ) : (
          <LoaderCircle className="spin" />
        )}
      </main>
    );
  if (!auth.user) return <AuthScreen setup={auth.needs_setup} onDone={(user) => setAuth({ needs_setup: false, user })} />;
  const logout = () => api("/auth/logout", {}).finally(() => setAuth({ needs_setup: false, user: null }));
  // key remounts the studio so one account's open course never shows for the next.
  return <Studio key={auth.user.id} user={auth.user} onUser={(user) => setAuth({ needs_setup: false, user })} onLogout={logout} />;
}

function Studio({ user, onUser, onLogout }: { user: User; onUser: (user: User) => void; onLogout: () => void }) {
  const [status, setStatus] = useState<Status>(),
    [courses, setCourses] = useState<CourseSummary[]>([]),
    [course, setCourse] = useState<Course>(),
    [loading, setLoading] = useState(true),
    [notice, setNotice] = useState(""),
    [target, setTarget] = useState<ResultTarget>(),
    [newCourse, setNewCourse] = useState(false),
    [draft, setDraft] = useState<CourseDraft>(),
    [mobile, setMobile] = useState(false),
    [view, setView] = useState<View>("learn");
  const courseId = useRef<string | undefined>(undefined),
    viewRef = useRef<View>("learn");
  useEffect(() => {
    viewRef.current = view;
  }, [view]);
  const storageKey = "zhixing-course:" + user.id;
  const reload = useCallback(async () => {
    const [s, c] = await Promise.all([api<Status>("/status"), api<CourseSummary[]>("/courses")]);
    setStatus(s);
    setCourses(c);
    if (courseId.current && !c.some((x) => x.id === courseId.current)) {
      setCourse(undefined);
      courseId.current = undefined;
      localStorage.removeItem(storageKey);
    }
    return c;
  }, [storageKey]);
  const load = async (id: string) => {
    const value = await api<Course>(`/courses/${id}`);
    setCourse(value);
    courseId.current = id;
    localStorage.setItem(storageKey, id);
  };
  // Every finished task refreshes the course it touched, even on failure:
  // lessons and pretest grades are saved before later steps that may fail.
  const finished = async (t: Task) => {
    const result = (t.result || {}) as TaskResult;
    const id = result.course_id || (t.course_id && t.course_id !== "new" ? t.course_id : undefined);
    if (t.action === "create") {
      if (t.status === "completed") setDraft(undefined);
      else setNewCourse(true);
    }
    await reload().catch(() => undefined);
    if (!id) return;
    const here = viewRef.current === "learn";
    if (here && (t.status === "completed" || id === courseId.current)) await load(id).catch(() => undefined);
    else if (id === courseId.current) await load(id).catch(() => undefined);
    if (t.status === "cancelled") setNotice("任务已取消，已保存的学习进度不受影响。");
    if (t.status !== "completed") return;
    setNotice(here ? "AI 已完成审核并更新学习记录。" : "AI 已完成，回到“我的学习”即可查看结果。");
    const action = result.action || t.action || "";
    if (JUMPS.has(action)) setTarget({ course_id: id, unit_id: result.unit_id, action, epoch: Date.now() });
  };
  const runner = useTaskRunner(finished);
  const { busy, task, error, setError } = runner;
  useEffect(() => {
    reload()
      .then(async (list) => {
        const saved = localStorage.getItem(storageKey);
        const id = list.some((c) => c.id === saved) ? saved : list[0]?.id;
        if (id) await load(id);
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [reload, storageKey]);
  // Course load can reject; without the catch the click looked like a dead button.
  const open = async (id: string) => {
    setError("");
    try {
      await load(id);
      setView("learn");
      setMobile(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "课程读取失败");
    }
  };
  const go = (next: View) => {
    setView(next);
    setMobile(false);
    setError("");
  };
  const action = (path: string, body: object) => {
    if (!course || busy) return;
    setNotice("");
    runner.start(`/courses/${course.id}/${path}`, body as Record<string, unknown>);
  };
  const changed = () => {
    reload().catch((e) => setError(e.message));
  };
  const refreshStatus = () => {
    api<Status>("/status").then(setStatus).catch(() => undefined);
  };
  const admin = user.role === "admin";
  const crumb = {
    learn: course?.title || "学习概览",
    progress: "学习进度",
    notebook: "错题本",
    sources: "学习资料",
    teacher: "教师审核",
    settings: "设置",
  }[view];
  const due = courses.reduce((n, c) => n + (c.progress?.notebook_due || 0), 0);
  const aiLabel = status?.configured ? (
    <span className="private-label">AI 服务已连接</span>
  ) : admin ? (
    <button className="secondary small" onClick={() => go("settings")}>
      填写 DeepSeek 密钥
    </button>
  ) : (
    <span className="private-label">等待管理员配置 AI 服务</span>
  );
  const nav = (id: View, label: string, icon: React.ReactNode, badge = 0) => (
    <button className={"course-nav " + (view === id ? "active" : "")} aria-current={view === id ? "page" : undefined} onClick={() => go(id)}>
      {icon}
      <span>{label}</span>
      {badge > 0 && (
        <span className="nav-badge" aria-label={badge + " 道待复习"}>
          {badge}
        </span>
      )}
    </button>
  );
  const page =
    view === "progress" ? (
      <ProgressPage onOpen={open} onReview={() => go("notebook")} onChanged={changed} onError={setError} />
    ) : view === "notebook" ? (
      <NotebookPage courses={courses} onChanged={changed} onError={setError} />
    ) : view === "sources" ? (
      <SourcesPage onError={setError} />
    ) : view === "teacher" && admin ? (
      <TeacherPage onChanged={changed} />
    ) : view === "settings" ? (
      <SettingsPage user={user} onUser={onUser} onStatus={refreshStatus} />
    ) : course ? (
      <LearningWorkspace
        key={course.id}
        course={course}
        working={busy}
        action={action}
        resultTarget={target}
        onTargetUsed={() => setTarget(undefined)}
        onError={setError}
        onTrace={() => setNotice("讲义、引用和评分依据均由 AI 生成并保留在学习记录中。")}
      />
    ) : (
      <div className="open-home">
        <h1>选择一个学习主题</h1>
        <p>所有知识点都可以直接打开。先修关系用于解释背景和推荐顺序，不会阻止你学习。</p>
        {loading ? (
          <LoaderCircle className="spin" />
        ) : courses.length ? (
          courses.map((c) => (
            <button className="course-card" key={c.id} onClick={() => open(c.id)}>
              <BookOpen />
              <span>
                <strong>{c.title}</strong>
                <small>
                  {c.units.length} 个知识点 · {courseStatusLabel(c.status)}
                </small>
              </span>
              <ArrowRight />
            </button>
          ))
        ) : (
          <button className="primary" onClick={() => setNewCourse(true)}>
            开始新学习 <Plus size={17} />
          </button>
        )}
      </div>
    );
  return (
    <div className="app-shell open-app">
      <aside className={"sidebar " + (mobile ? "mobile-open" : "")}>
        <a
          className="brand"
          href="#"
          onClick={(e) => {
            e.preventDefault();
            setCourse(undefined);
            courseId.current = undefined;
            go("learn");
          }}
        >
          <span className="brand-symbol">知</span>
          <span>
            知行<span className="brand-sub">AI 学习工作室</span>
          </span>
        </a>
        <div className="sidebar-label">我的学习</div>
        {courses.map((c) => (
          <button className={"course-nav " + (view === "learn" && c.id === course?.id ? "active" : "")} key={c.id} onClick={() => open(c.id)}>
            <BookOpen size={17} />
            <span>{c.title}</span>
          </button>
        ))}
        <button className="primary small" onClick={() => setNewCourse(true)}>
          <Plus size={16} /> 新建主题
        </button>
        <div className="sidebar-label">管理</div>
        {nav("progress", "学习进度", <BarChart3 size={17} />)}
        {nav("notebook", "错题本", <NotebookPen size={17} />, due)}
        {nav("sources", "学习资料", <Library size={17} />)}
        {admin && nav("teacher", "教师审核", <ClipboardCheck size={17} />)}
        {nav("settings", admin ? "设置与账号" : "账号设置", <Settings size={17} />)}
        <div className="sidebar-user">
          <span>
            <strong>{user.display_name}</strong>
            <small>{admin ? "管理员" : "学习者"}</small>
          </span>
          <button className="icon-button" aria-label="退出登录" title="退出登录" onClick={onLogout}>
            <LogOut size={17} />
          </button>
        </div>
      </aside>
      <main className="main">
        <header className="topbar">
          <button className="icon-button mobile-toggle" aria-label="打开导航" onClick={() => setMobile(!mobile)}>
            <Compass size={19} />
          </button>
          <div className="breadcrumb">
            学习工作室 <ArrowRight size={13} /> {crumb}
          </div>
          {aiLabel}
        </header>
        <div className="page">
          <OperationFeedback
            busy={busy}
            task={task}
            error={error}
            notice={notice}
            onCancel={runner.cancel}
            onResult={
              task?.status === "completed" && view !== "learn"
                ? () => {
                    const id = (task.result as TaskResult | undefined)?.course_id;
                    if (id) open(id);
                  }
                : undefined
            }
          />
          {page}
        </div>
      </main>
      {view === "learn" && course && <SelectionAssistant course={course} working={busy} action={action} onError={setError} />}
      {newCourse && (
        <NewCourse
          busy={busy}
          draft={draft}
          onClose={() => setNewCourse(false)}
          onSubmit={(data) => {
            setDraft(data);
            setNewCourse(false);
            go("learn");
            setNotice("");
            runner.start("/courses", data).then((ok) => ok || setNewCourse(true));
          }}
        />
      )}
    </div>
  );
}
