# 知行 API 契约（1.3.1）

服务默认监听 `http://127.0.0.1:8877`。除公开接口外，所有 `/api/*` 请求需要登录 Cookie；写请求（非 GET/HEAD/OPTIONS）必须来自同源页面。

## 认证与错误

- 会话 Cookie：`zhixing_session`，HttpOnly、SameSite=Strict，30 天有效；服务端只保存令牌哈希。
- 登录失败 5 次锁定该用户名 60 秒。
- 未登录：`401 {detail, code:"login_required"}`。
- 跨站写请求：`403 {detail:"不允许跨站请求。"}`。
- 参数校验失败：`422`，不回显提交内容。
- 模型/网络失败：任务状态 `failed`，`error` 为可读原因；已保存进度保留。

公开接口：`GET /api/status`、`GET /api/report`、`GET /api/experiments`、`/api/auth/*`。

## 任务模型

耗时操作返回 `task_id`，通过 `GET /api/tasks/{id}` 或 SSE 获取状态：

```json
{
  "id": "…",
  "action": "diagnostic",
  "course_id": "…",
  "status": "queued|running|completed|failed|cancelled",
  "progress": ["正在生成前测题"],
  "result": {},
  "error": null,
  "created_at": "…",
  "started_at": "…",
  "finished_at": "…"
}
```

- `DELETE /api/tasks/{id}`：取消排队或运行中的任务。
- 单个任务超过 20 分钟自动停止并标记 `failed`。
- 同一 `request_id` 幂等，重复提交返回同一任务。

## 课程

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/courses` | 当前账号的课程摘要与学习进度 |
| POST | `/api/courses` | 新建课程，返回 `task_id` |
| GET | `/api/courses/{id}` | 课程详情（不含提交前答案） |
| PATCH | `/api/courses/{id}` | 修改课程标题 |
| DELETE | `/api/courses/{id}` | 删除课程及其错题、任务、审核记录 |
| GET | `/api/courses/{id}/export` | 导出脱敏 JSON |
| GET | `/api/courses/{id}/units/{unit_id}` | 单元工作区（讲义、练习、历史、消息） |
| POST | `/api/courses/{id}/clarify` | 回答诊断澄清问题并重建前测 |
| POST | `/api/courses/{id}/diagnostic` | 提交前测，生成计划、首单元讲义与练习 |
| POST | `/api/courses/{id}/lesson` | 继续、补讲、刷新或复习某单元 |
| POST | `/api/courses/{id}/answers` | 提交练习并批改 |
| POST | `/api/courses/{id}/chat` | 划选内容提问，支持 1–3 级提示 |
| POST | `/api/courses/{id}/appeals` | 对单题申诉一次，AI 重新批改并保留原分 |
| GET | `/api/courses/{id}/notebook` | 错题本列表 |
| POST | `/api/courses/{id}/notebook/{item_id}/review` | 错题复习作答 |
| GET | `/api/courses/{id}/assessment?kind=pre|post|delayed` | 获取阶段测验题 |
| POST | `/api/courses/{id}/assessment` | 提交阶段测验 |

### `POST /api/courses`

```json
{
  "topic": "单变量微积分",
  "background": "学过高中数学",
  "goal": "掌握极限与导数基础",
  "hours_per_week": 3,
  "minutes_per_session": 30,
  "preference": "examples",
  "search_web": false,
  "source_ids": [],
  "request_id": "uuid"
}
```

`hours_per_week` 为大于 0、不超过 100 的数值，支持 2.5、3、3.5 等；`minutes_per_session` 为 5–240 的整数。

### 题目与反馈

公开题目不包含 `expected_answer`、`solution`、`verification` 等提交前答案字段：

```json
{
  "id": "q1",
  "prompt": "求 lim(x→1) (x²-1)/(x-1)",
  "kind": "expression|open",
  "unit_id": "u02",
  "difficulty": "基础|应用|解释",
  "rubric": [{"criterion": "结果正确", "points": 1}],
  "hints": ["先因式分解"]
}
```

批改结果：

```json
{
  "score": 0.6,
  "decision": "remedial|advance|complete",
  "items": [{
    "question_id": "q1",
    "score": 0.6,
    "feedback": "…",
    "evidence": "…",
    "error_type": "…",
    "original_score": 0.6,
    "appeal": {},
    "teacher_review": {"action": "revise", "reason": "…", "by": "admin", "at": "…"}
  }],
  "explanation": "…",
  "next_unit_id": "u02",
  "ai_uncertain": true,
  "ai_review": {"verdict": "uncertain", "advice": "…", "issues": []}
}
```

`needs_human_review` 在存储结果中恒为 `false`；不确定性通过 `ai_uncertain` + `ai_review` 表达。只有带 `teacher_review` 的分数经过教师确认。

## 资料

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/sources` | 当前账号可见资料（内置教材共享） |
| POST | `/api/sources/upload` | 上传 txt/md/pdf/docx，最大 4 MB |
| POST | `/api/sources/url` | 抓取公开网页正文 |
| DELETE | `/api/sources/{id}` | 删除自己的资料；内置资料不可删 |

## 账号、设置与管理员

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/auth/state` | 是否首次使用、当前用户 |
| POST | `/api/auth/setup` | 创建第一个管理员 |
| POST | `/api/auth/login` / `logout` | 登录 / 退出 |
| PATCH | `/api/me` | 修改显示名 |
| POST | `/api/me/password` | 修改密码，撤销其他会话 |
| GET | `/api/settings/provider` | 模型配置状态（不返回密钥） |
| PUT | `/api/settings/provider` | 验证并保存/清除密钥 |
| POST | `/api/settings/provider/test` | 测试密钥 |
| GET/POST | `/api/users` | 管理员查看/创建账号 |
| PATCH | `/api/users/{id}` | 修改显示名、角色、停用状态 |
| POST | `/api/users/{id}/password` | 重置密码 |
| DELETE | `/api/users/{id}` | 删除账号及其课程 |
| GET | `/api/reviews` | 自己的审核记录（不含作答） |
| GET | `/api/teacher/reviews` | 管理员查看全部待审/已审记录 |
| POST | `/api/reviews/{id}/resolve` | 管理员确认或改分 |
| GET | `/api/teacher/courses/{id}/trace` | 管理员查看角色调用轨迹 |
| POST | `/api/courses/{id}/rubric` | 管理员修改作业量规 |
| GET | `/api/admin/progress` | 学员进度统计（不含作答） |
| GET | `/api/admin/backup` | 下载 SQLite 备份 |
| GET | `/api/admin/logs` | 最近 256 KB 脱敏日志 |
| GET | `/api/system/info` | 版本、数据路径、用量估算 |
| POST | `/api/system/shutdown` | 网页退出程序（仅桌面启动器） |

## 模块边界

| 模块 | 职责 |
| --- | --- |
| `learning/api.py` | HTTP 路由、认证、同源校验、静态资源 |
| `learning/engine.py` | 五角色编排、状态机、任务与评分 |
| `learning/knowledge.py` | 12 单元课程加载与图谱校验 |
| `learning/mathcheck.py` | SymPy 受限子进程核验 |
| `learning/review_policy.py` | AI 审核与教师通道字段 |
| `learning/progression.py` | 掌握度与下一单元 |
| `learning/sources.py` | 上传、网页抓取、检索 |
| `learning/accounts.py` | 账号、密码哈希、会话 |
| `learning/db.py` | SQLite 文档与任务存储 |
| `learning/provider.py` | DeepSeek 网关、重试、脱敏 |
| `frontend/` | React 学生端与教师端 |

## 版本说明

- 1.3.1：修复非微积分主题在前测后无法规划；保留前测结果并从规划步骤续跑。
- 1.3.0：教师审核、单题申诉、学员进度、任务取消/超时、备份与错误日志。
- 1.2.0：多账号与权限隔离、网页密钥设置、学习进度、错题本、阶段测验。
