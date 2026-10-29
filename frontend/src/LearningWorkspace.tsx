import { useEffect, useRef, useState } from "react";
import {
  ArrowRight,
  BookOpen,
  MessageCircle,
  RefreshCw,
  LoaderCircle,
} from "lucide-react";
import { api } from "./api";
import type { Course, Workspace, Feedback, FeedbackItem, AIReview } from "./api";
import SymbolInput from "./SymbolInput";
import Markdown from "./Markdown";
import Plot from "./Plot";
import Questions from "./Questions";
import AssessmentPanel from "./AssessmentPanel";

export type ResultTarget = { course_id?: string; unit_id?: string; action?: string; epoch: number };
export function ReviewAdvice({ review }: { review?: AIReview }) {
  return review ? (
    <div className="ai-advice">
      <strong>
        AI 自动审核 ·{" "}
        {review.verdict === "accepted"
          ? "通过"
          : review.verdict === "revise"
            ? "建议修正"
            : "有保留意见"}
      </strong>
      <Markdown text={review.advice} />
      {review.issues.map((issue, i) => (
        <p key={i}>{issue}</p>
      ))}
    </div>
  ) : null;
}
export function FeedbackView({
  feedback,
  title = "练习反馈",
  onAppeal,
  busy = false,
}: {
  feedback: Feedback;
  title?: string;
  onAppeal?: (questionId: string, reason: string) => void;
  busy?: boolean;
}) {
  return (
    <section className="feedback-view">
      <div className="section-title">
        <h3>{title}</h3>
        <strong className="score">
          {Math.round(feedback.score * 100)}
          <small> / 100</small>
        </strong>
      </div>
      {feedback.ai_uncertain ? (
        <span className="badge amber">AI 已审核 · 建议核对</span>
      ) : (
        <span className="badge">AI 已自动审核</span>
      )}
      <Markdown text={feedback.explanation || ""} />
      <ReviewAdvice review={feedback.ai_review} />
      {feedback.items?.map((item, i) => (
        <div className="feedback-item" key={item.question_id}>
          <strong>
            第 {i + 1} 题 · {Math.round(item.score * 100)} 分
            {item.original_score !== undefined && item.original_score !== item.score && (
              <small className="muted"> （原 {Math.round(item.original_score * 100)} 分）</small>
            )}
          </strong>
          {item.teacher_review && <span className="badge">教师已{item.teacher_review.action === "revise" ? "改分" : "确认"}</span>}
          <Markdown text={item.feedback} />
          {item.teacher_review?.reason && <p className="muted">教师说明：{item.teacher_review.reason}</p>}
          <AppealBox item={item} busy={busy} onAppeal={onAppeal} />
          {item.solution && (
            <details>
              <summary>参考解答</summary>
              <Markdown text={item.solution} />
            </details>
          )}
          {item.evidence !== undefined && (
            <details>
              <summary>核验依据</summary>
              <pre>{JSON.stringify(item.evidence, null, 2)}</pre>
            </details>
          )}
        </div>
      ))}
    </section>
  );
}
// One appeal per question: the AI re-grades it with the learner's reason; the original score stays visible.
function AppealBox({ item, busy, onAppeal }: { item: FeedbackItem; busy: boolean; onAppeal?: (questionId: string, reason: string) => void }) {
  const [open, setOpen] = useState(false),
    [reason, setReason] = useState("");
  if (item.appeal)
    return (
      <p className="muted">
        已申诉：AI 重新批改 {Math.round(item.appeal.original_score * 100)} → {Math.round(item.appeal.regrade_score * 100)} 分。管理员可在教师审核中复核。
      </p>
    );
  if (!onAppeal || item.teacher_review) return null;
  if (!open)
    return (
      <button className="text-button" disabled={busy} onClick={() => setOpen(true)}>
        对本题评分有疑问
      </button>
    );
  return (
    <form
      className="appeal-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (reason.trim()) onAppeal(item.question_id, reason.trim());
      }}
    >
      <label>
        说明你的理由（AI 会据此重新批改这一题，每题一次）
        <textarea rows={2} maxLength={2000} required value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <div className="button-row">
        <button className="secondary small" disabled={busy || !reason.trim()}>
          请 AI 重新批改
        </button>
        <button type="button" className="text-button" onClick={() => setOpen(false)}>
          取消
        </button>
      </div>
    </form>
  );
}

// The diagnostic agent may ask one question before the pretest; answering it rebuilds the pretest.
function Clarify({ course, working, action }: { course: Course; working: boolean; action: (path: string, body: object) => void }) {
  const key = "zhixing-clarify-" + course.id;
  const [answer, setAnswer] = useState(() => localStorage.getItem(key) || "");
  return (
    <form
      className="clarify-form"
      onSubmit={(e) => {
        e.preventDefault();
        if (answer.trim()) action("clarify", { answers: answer.trim() });
      }}
    >
      <p>开始前测之前，AI 想先了解一点：</p>
      {course.clarifications!.map((q, i) => (
        <blockquote key={i}>
          <Markdown text={q} />
        </blockquote>
      ))}
      <label htmlFor="clarify-answer">我的回答</label>
      <SymbolInput
        id="clarify-answer"
        topic={course.topic}
        rows={3}
        required
        value={answer}
        onChange={(value) => {
          setAnswer(value);
          localStorage.setItem(key, value);
        }}
        placeholder="例如：学过函数图像，但没学过极限"
      />
      <button className="primary" disabled={working || !answer.trim()}>
        提交并生成前测
      </button>
    </form>
  );
}

export default function LearningWorkspace({
  course,
  working,
  action,
  resultTarget,
  onError,
  onTrace,
  onTargetUsed,
}: {
  course: Course;
  working: boolean;
  action: (path: string, body: object) => void;
  resultTarget?: ResultTarget;
  onError: (text: string) => void;
  onTrace: () => void;
  onTargetUsed?: () => void;
}) {
  const saved = () => {
    const value = localStorage.getItem("zhixing-unit-" + course.id);
    return value && course.units.some((u) => u.id === value)
      ? value
      : course.current_unit_id || course.units[0]?.id || "";
  };
  const [unitId, setUnitId] = useState(saved),
    [workspace, setWorkspace] = useState<Workspace>(),
    [loading, setLoading] = useState(false),
    [loadError, setLoadError] = useState(""),
    [tab, setTab] = useState("lesson");
  const surface = useRef<HTMLDivElement>(null);
  const select = (id: string) => {
    setUnitId(id);
    setTab("lesson");
    localStorage.setItem("zhixing-unit-" + course.id, id);
  };
  useEffect(() => {
    let active = true;
    setLoading(true);
    setLoadError("");
    api<Workspace>(`/courses/${course.id}/units/${unitId}`)
      .then((value) => {
        if (active) setWorkspace(value);
      })
      .catch((e) => {
        if (active) {
          setWorkspace(undefined);
          setLoadError(e.message);
          onError(e.message);
        }
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [course, unitId]);
  useEffect(() => {
    // A finished task may belong to another course; only jump when it is this one.
    if (!resultTarget || (resultTarget.course_id && resultTarget.course_id !== course.id)) return;
    onTargetUsed?.();
    if (resultTarget.unit_id) select(resultTarget.unit_id);
    setTab(
      resultTarget.action === "answers" || resultTarget.action === "appeal"
        ? "feedback"
        : ["diagnostic", "clarify", "create"].includes(resultTarget.action || "")
          ? "pretest"
          : "lesson",
    );
    requestAnimationFrame(() =>
      surface.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  }, [resultTarget?.epoch]);
  const unit = course.units.find((u) => u.id === unitId),
    ws = workspace?.unit.id === unitId ? workspace : undefined;
  const generate = (mode: string) => {
    if (
      mode === "remedial" &&
      ws?.assignment &&
      !ws.assignment.submitted &&
      !window.confirm(
        "当前练习尚未提交。生成补讲会更换本知识点练习，是否继续？",
      )
    )
      return;
    action("lesson", { unit_id: unitId, mode });
  };
  return (
    <>
      <div className="page-heading compact">
        <div>
          <h1>{course.title}</h1>
          <p>{course.profile?.goal}</p>
        </div>
        <button className="secondary small" onClick={onTrace}>
          <BookOpen size={16} /> 学习依据
        </button>
      </div>
      <div className="open-workspace">
        <aside className="knowledge-map">
          <h3>
            知识地图 <small>{course.units.length}</small>
          </h3>
          <div className="map-units">
            {course.units.map((u, i) => {
              const value = course.mastery?.[u.id],
                status = typeof value === "object" ? value.status : "";
              return (
                <button
                  type="button"
                  key={u.id}
                  className={u.id === unitId ? "selected" : ""}
                  onClick={() => select(u.id)}
                >
                  <span>{String(i + 1).padStart(2, "0")}</span>
                  <div>
                    <strong>{u.title}</strong>
                    <small>
                      {status === "mastered"
                        ? "已掌握"
                        : status === "learning"
                          ? "继续巩固"
                          : status === "review"
                            ? "AI 建议巩固"
                            : "尚未评估"}
                      {course.recommended_unit_id === u.id ? " · 推荐" : ""}
                    </small>
                  </div>
                </button>
              );
            })}
          </div>
        </aside>
        <div
          className="learning-surface"
          ref={surface}
          data-learning-surface
          data-unit-id={unitId}
        >
          <div className="workspace-heading">
            <div>
              <h2>{unit?.title}</h2>
              {!!unit?.prerequisites.length && (
                <p className="small muted">
                  关联知识：
                  {unit.prerequisites
                    .map((id) => course.units.find((u) => u.id === id)?.title)
                    .join("、")}
                </p>
              )}
            </div>
            <button
              className="secondary small"
              onClick={() =>
                window.dispatchEvent(
                  new CustomEvent("zhixing-ask", {
                    detail: { unit_id: unitId },
                  }),
                )
              }
            >
              <MessageCircle size={17} /> 提问
            </button>
          </div>
          <div className="lesson-tabs">
            {[
              ["lesson", "讲义"],
              ["practice", "练习"],
              ["feedback", "反馈"],
              ["pretest", "起点测评"],
              ...(course.builtin ? [["assessment", "阶段测验"]] : []),
            ].map(([id, label]) => (
              <button
                key={id}
                className={tab === id ? "selected" : ""}
                onClick={() => setTab(id)}
              >
                {label}
              </button>
            ))}
          </div>
          {tab === "assessment" ? (
            <AssessmentPanel course={course} onError={onError} />
          ) : loading ? (
            <div className="workspace-loading">
              <LoaderCircle className="spin" /> 正在读取知识点
            </div>
          ) : loadError ? (
            <p role="alert">{loadError}</p>
          ) : (
            <>
              {tab === "lesson" && (
                <article className="workspace-article">
                  {ws?.lesson ? (
                    <>
                      <ReviewAdvice review={ws.lesson.ai_review} />
                      <Markdown text={ws.lesson.body} />
                      {ws.lesson.plot && <Plot spec={ws.lesson.plot} />}{" "}
                      {ws.lesson.examples?.map((ex, i) => (
                        <div className="example" key={i}>
                          <h3>例题 {i + 1}</h3>
                          <Markdown text={ex.question} />
                          <details>
                            <summary>思路与解答</summary>
                            <Markdown text={ex.solution} />
                          </details>
                        </div>
                      ))}
                      {ws.lesson.misconceptions?.map((text, i) => (
                        <Markdown key={i} text={text} />
                      ))}
                      <details>
                        <summary>参考资料</summary>
                        {ws.lesson.citations?.map((id) => {
                          const s = course.sources?.find(
                            (s) => s.id === id || s.record_ids?.includes(id),
                          );
                          return (
                            <p key={id}>
                              {s?.url ? (
                                <a
                                  href={s.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {s.title}
                                </a>
                              ) : (
                                s?.title || "引用待核验"
                              )}
                            </p>
                          );
                        })}
                      </details>
                    </>
                  ) : (
                    <>
                      <Markdown text={unit?.content || ""} />
                      {unit?.objectives.map((o, i) => (
                        <p key={i}>{o}</p>
                      ))}
                      <button
                        className="primary"
                        disabled={working}
                        onClick={() => generate("review")}
                      >
                        <BookOpen size={17} /> 生成讲解与练习
                      </button>
                    </>
                  )}
                </article>
              )}
              {tab === "practice" &&
                (ws?.assignment ? (
                  ws.assignment.submitted ? (
                    <div>
                      <p>本次练习已提交。</p>
                      <button
                        className="secondary"
                        onClick={() => setTab("feedback")}
                      >
                        查看反馈 <ArrowRight size={16} />
                      </button>
                    </div>
                  ) : (
                    <Questions
                      key={ws.assignment.id}
                      draftKey={course.id + "-" + ws.assignment.id}
                      topic={course.topic}
                      questions={ws.assignment.questions}
                      busy={working}
                      submit={(answers) =>
                        action("answers", {
                          unit_id: unitId,
                          assignment_id: ws.assignment!.id,
                          answers,
                        })
                      }
                    />
                  )
                ) : (
                  <button
                    className="primary"
                    disabled={working}
                    onClick={() => generate("review")}
                  >
                    <BookOpen size={17} /> 准备练习
                  </button>
                ))}
              {tab === "feedback" &&
                (ws?.last_feedback ? (
                  <>
                    <FeedbackView
                      feedback={ws.last_feedback}
                      busy={working}
                      onAppeal={
                        ws.last_history_id
                          ? (question_id, reason) => action("appeals", { history_id: ws.last_history_id, question_id, reason })
                          : undefined
                      }
                    />
                    <button
                      className="secondary"
                      disabled={working}
                      onClick={() => generate("remedial")}
                    >
                      <RefreshCw size={16} /> 补讲与新练习
                    </button>
                  </>
                ) : (
                  <p className="muted">本知识点还没有练习反馈。</p>
                ))}
              {tab === "pretest" &&
                (course.diagnostic_result ? (
                  <>
                    <p>起点测评已完成。</p>
                    {course.status === "diagnostic" && (
                      // Grading is saved before planning; a failed plan is retried without re-grading.
                      <div>
                        <p className="small muted">课程规划尚未完成，评分已保存，可直接重新规划。</p>
                        <button
                          className="primary"
                          disabled={working}
                          onClick={() => action("diagnostic", { answers: [] })}
                        >
                          <RefreshCw size={17} /> 继续规划课程
                        </button>
                      </div>
                    )}
                    {typeof course.diagnostic_result === "object" &&
                      course.diagnostic_result !== null &&
                      "score" in course.diagnostic_result && (
                        <FeedbackView
                          feedback={course.diagnostic_result as Feedback}
                        />
                      )}
                  </>
                ) : course.clarifications?.length ? (
                  <Clarify course={course} working={working} action={action} />
                ) : (
                  <Questions
                    key={course.id + "-diagnostic"}
                    draftKey={course.id + "-diagnostic"}
                    topic={course.topic}
                    questions={course.diagnostic?.questions || []}
                    busy={working}
                    submit={(answers) => action("diagnostic", { answers })}
                  />
                ))}
            </>
          )}
          <div className="workspace-footer">
            {ws?.lesson && (
              <button
                className="text-button"
                onClick={() =>
                  setTab(tab === "practice" ? "lesson" : "practice")
                }
              >
                {tab === "practice" ? "返回讲义" : "进入练习"}{" "}
                <ArrowRight size={16} />
              </button>
            )}
            {ws?.next_unit_id && (
              <button
                className="primary small"
                onClick={() => select(ws.next_unit_id!)}
              >
                下一个知识点 <ArrowRight size={16} />
              </button>
            )}
          </div>
        </div>
      </div>
    </>
  );
}
