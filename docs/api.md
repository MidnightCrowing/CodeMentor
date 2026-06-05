# CodeMentor 后端 API 文档

> 面向前端开发的完整接口文档。后端基于 FastAPI 实现，所有接口（除流式 `/chat` 外）均返回统一 JSON 格式。

---

## 一、基础约定

### 1.1 Base URL

```
{HOST}/api/v1
```

本地默认端口 `8000`，如 `http://localhost:8000/api/v1`。

### 1.2 鉴权

后端从请求中按以下优先级提取 `user_id`：

1. `Authorization: Bearer <user_id>` 请求头（**推荐**）
2. `X-User-Id: <user_id>` 请求头
3. Cookie `user_id=<user_id>`

> 说明：当前未启用 JWT 等加密 Token，`Bearer` 后直接传 `user_id` 字符串即可。前端可使用其中任意一种方式，全局保持一致即可。

未携带任何身份凭证 → `401 Unauthorized`。
携带但用户不存在 → `403 Forbidden`。

### 1.3 角色与权限

| 角色 | 权重 | 可访问范围 |
|---|---|---|
| `student` | 1 | 注册、聊天、查询本人历史/会话/用量 |
| `teacher` | 2 | 学生端全部接口 + 分析/统计/批量导出 |
| `admin` | 3 | 教师端全部接口 + 管理员强制运行 |

权限是**累加**的：teacher 可调用 student 接口，admin 可调用 teacher 接口。
权限不足 → `403 Forbidden`。

### 1.4 统一响应格式

所有非流式接口均返回如下结构（HTTP 状态码均为 `200`，除非命中鉴权/限流/参数校验异常）：

**成功**
```json
{
  "code": 0,
  "message": "ok",
  "data": { /* 具体数据 */ }
}
```

**业务失败**
```json
{
  "code": 1,
  "message": "错误信息",
  "data": null
}
```

> 前端处理逻辑建议：
> - HTTP `200` 且 `code === 0` → 成功，使用 `data`
> - HTTP `200` 且 `code === 1` → 业务校验失败（如「会话不存在」「模型不可用」），展示 `message`
> - HTTP `4xx/5xx` → 框架级错误，统一弹窗或跳登录

### 1.5 HTTP 状态码与异常返回

非 `200` 响应同样使用 `{code, message, data}` 结构：

| HTTP 状态 | 触发场景 | message 示例 |
|---|---|---|
| `400` | 请求体/Query 参数校验失败 | `参数错误: message` |
| `401` | 未携带身份凭证 | `缺少身份凭证` |
| `403` | 用户不存在 或 权限不足 | `用户不存在` / `权限不足` |
| `404` | 路由不存在 | FastAPI 默认 |
| `429` | 触发限流 | `请求过于频繁，请稍后再试` |
| `500` | 未处理的服务端异常 | `请求处理失败，请稍后重试` |

### 1.6 限流

- `POST /api/v1/chat`：**15 次 / 分钟**（按用户身份计数；未登录回退到 IP）。
- `teacher` / `admin` 角色调用 `/chat` 不受限流。
- 超限返回 HTTP `429`，body 见 1.5。

### 1.7 CORS

后端通过 `app.cors_origins` 白名单控制，开发联调请联系后端将本地域名加入白名单；正式环境前端域名需提前申请。

### 1.8 通用数据类型

| 类型 | 说明 | 示例 |
|---|---|---|
| `datetime` | ISO 8601，带 UTC 时区 | `"2026-05-24T03:21:18.123456+00:00"` |
| `uuid` | 标准 UUID 字符串 | `"3fa85f64-5717-4562-b3fc-2c963f66afa6"` |
| `date` | `YYYY-MM-DD` | `"2026-05-24"` |

---

## 二、接口分组速览

| 分组 | 接口数 | 主要使用方 |
|---|---|---|
| [用户注册与身份](#三用户注册与身份) | 3 | 学生/通用 |
| [对话模型](#四对话模型) | 1 | 学生 |
| [会话管理](#五会话管理) | 4 | 学生 |
| [流式聊天](#六流式聊天) | 1 | 学生 |
| [问答记录与用量](#七问答记录与用量) | 2 | 学生 |
| [教师端 - 学生与班级](#八教师端---学生与班级) | 2 | 教师 |
| [教师端 - 学习分析](#九教师端---学习分析) | 2 | 教师 |
| [教师端 - 行为统计](#十教师端---行为统计) | 6 | 教师 |
| [教师端 - 批量导出](#十一教师端---批量导出报告) | 5 | 教师 |
| [管理员](#十二管理员) | 1 | 管理员 |
| [系统](#十三系统) | 1 | 通用 |

---

## 三、用户注册与身份

### 3.1 临时注册

> 用于学生快速进入使用（不绑定学号、密码）。

- **POST** `/api/v1/register/temp`
- **鉴权**：无
- **请求体**

  | 字段 | 类型 | 必填 | 约束 | 说明 |
  |---|---|---|---|---|
  | `user_id` | string | ✅ | 1-100 字符 | 自定义用户 ID（保证唯一） |

- **请求示例**

  ```json
  POST /api/v1/register/temp
  Content-Type: application/json

  {"user_id": "stu_demo_001"}
  ```

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": {"user_id": "stu_demo_001"}}
  ```

- **常见失败**：账号已存在 → `{"code": 1, "message": "账号已存在", "data": null}`

---

### 3.2 学生正式注册

- **POST** `/api/v1/register`
- **鉴权**：无
- **请求体**

  | 字段 | 类型 | 必填 | 约束 | 说明 |
  |---|---|---|---|---|
  | `real_name` | string | ✅ | 1-100 | 学生真实姓名 |
  | `student_no` | string | ✅ | 6-50 | 学号（同时作为 `user_id`） |
  | `password` | string | ✅ | 6-100 | 登录密码（后端会哈希存储） |

- **请求示例**

  ```json
  POST /api/v1/register
  Content-Type: application/json

  {
    "real_name": "张三",
    "student_no": "2024010101",
    "password": "Passw0rd!"
  }
  ```

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": {"user_id": "2024010101"}}
  ```

- **常见失败**：账号已存在（`student_no` 已被注册或冲突 `user_id`）。

---

### 3.3 获取当前登录用户信息

- **GET** `/api/v1/whoami`
- **鉴权**：`student+`

- **响应 `data` 结构**

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `user_id` | string | 用户 ID |
  | `role` | string | `student` / `teacher` / `admin` |
  | `created_at` | datetime | 注册时间 |

- **响应示例**

  ```json
  {
    "code": 0,
    "message": "ok",
    "data": {
      "user_id": "2024010101",
      "role": "student",
      "created_at": "2026-04-01T08:12:33.123456+00:00"
    }
  }
  ```

---

## 四、对话模型

### 4.1 获取可用模型列表

- **GET** `/api/v1/models`
- **鉴权**：无（公开）
- **响应 `data` 结构**

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `default_model` | string | 默认模型 ID（未指定 `model_id` 时使用） |
  | `models` | array | 全部可用模型 |
  | `models[].id` | string | 模型 ID，用于 `/chat` 的 `model_id` |
  | `models[].name` | string | 推荐显示名称 |
  | `models[].support_thinking` | bool | 是否支持思维链（`reasoning` 流） |

- **响应示例**

  ```json
  {
    "code": 0,
    "message": "ok",
    "data": {
      "default_model": "gpt-5-mini",
      "models": [
        {"id": "gpt-5-mini", "name": "GPT-5-Mini", "support_thinking": false},
        {"id": "Pro/zai-org/GLM-5", "name": "GLM-5", "support_thinking": true},
        {"id": "deepseek-v3.2", "name": "DeepSeek-V3.2 Free", "support_thinking": true}
      ]
    }
  }
  ```

---

## 五、会话管理

### 5.1 获取当前用户会话列表

- **GET** `/api/v1/sessions`
- **鉴权**：`student+`
- **Query**

  | 字段 | 类型 | 必填 | 默认 | 约束 | 说明 |
  |---|---|---|---|---|---|
  | `limit` | int | - | 20 | 1-100 | 每页条数 |
  | `offset` | int | - | 0 | ≥0 | 分页偏移 |

- **响应 `data` 结构**：`SessionOut[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `id` | string | 会话 ID（UUID 字符串） |
  | `title` | string | null | 会话标题（首次提问后由模型自动生成） |
  | `created_at` | datetime | 创建时间 |

- **响应示例**

  ```json
  {
    "code": 0,
    "message": "ok",
    "data": [
      {"id": "9c93...", "title": "如何理解 Python 装饰器", "created_at": "2026-05-23T01:11:00+00:00"},
      {"id": "8a21...", "title": "新会话", "created_at": "2026-05-22T08:00:00+00:00"}
    ]
  }
  ```

  > 按 `created_at` **倒序**返回。

---

### 5.2 批量删除历史会话

- **DELETE** `/api/v1/sessions/batch`
- **鉴权**：`student+`
- **Query**

  | 字段 | 类型 | 必填 | 约束 | 说明 |
  |---|---|---|---|---|
  | `days` | int | ✅ | ≥0 | 删除「N 天前及以前」的会话（`0` 表示删除当前时间之前的全部） |

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": "已删除 5 个会话"}
  ```

  ```json
  {"code": 0, "message": "ok", "data": "没有可删除的会话"}
  ```

  > 会话被物理删除；对应问答记录（`questions`）会被标记 `is_deleted=true`（软删）。

---

### 5.3 删除单个会话

- **DELETE** `/api/v1/sessions/{session_id}`
- **鉴权**：`student+`
- **路径参数**

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `session_id` | string | 目标会话 ID |

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": "会话已删除"}
  ```

- **失败示例**：`{"code": 1, "message": "会话不存在或无权访问", "data": null}`

---

### 5.4 重命名会话标题

- **PATCH** `/api/v1/sessions/{session_id}/title`
- **鉴权**：`student+`
- **路径参数**：同 5.3
- **请求体**

  | 字段 | 类型 | 必填 | 约束 | 说明 |
  |---|---|---|---|---|
  | `title` | string | ✅ | 1-100 | 新的会话标题 |

- **请求示例**

  ```json
  PATCH /api/v1/sessions/9c93.../title
  Content-Type: application/json

  {"title": "Python 装饰器学习"}
  ```

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": "会话标题已更新"}
  ```

---

## 六、流式聊天

### 6.1 POST `/api/v1/chat`（SSE 流式）

- **鉴权**：`student+`
- **限流**：15/分钟（teacher/admin 豁免）
- **响应**：`text/event-stream`（**不**遵循统一 JSON 格式）

#### 请求体

| 字段 | 类型 | 必填 | 约束/默认 | 说明 |
|---|---|---|---|---|
| `message` | string | ✅ | 1-8000 字符 | 用户消息内容 |
| `session_id` | string | - | null | 会话 ID。**为空时由后端创建新会话**，会话 ID 在 `session_meta` 事件中返回 |
| `dialog_id` | uuid | - | null | **重修指定问题**：传某条 `question.id`，该问及其后续问答会被软删，再以该问题为起点重新生成回答 |
| `model_id` | string | - | null（即用 `default_model`） | 指定模型 ID（必须存在于 `/models.models[].id`） |
| `enable_thinking` | bool | - | `true` | 是否开启深度思考（仅对 `support_thinking=true` 的模型生效） |

#### 请求示例

```json
POST /api/v1/chat
Authorization: Bearer 2024010101
Content-Type: application/json

{
  "session_id": null,
  "message": "解释一下 Python 中 *args 和 **kwargs 的区别",
  "model_id": "gpt-5-mini",
  "enable_thinking": false
}
```

#### SSE 事件协议

每条事件按以下格式（注意每条以 `\n\n` 结尾）：

```
data: {"type": "<event_type>", ...其他字段}\n\n
```

事件类型一览：

| `type` | 何时出现 | 携带字段 | 前端处理建议 |
|---|---|---|---|
| `session_meta` | 仅新会话首条流中、收到首个内容块前 | `session_id`: string, `title`: string | 持久化 `session_id`，并把侧边栏新会话标题刷新成 `title` |
| `reasoning` | 仅 `support_thinking=true` 且 `enable_thinking=true` 时 | `data`: string | 追加到「思考过程」UI（建议折叠展示） |
| `content` | 主答文本流（多次出现） | `data`: string | 拼接到当前回答气泡 |
| `error` | 任意时刻服务端异常 | `message`: string | 展示错误，并视情况保留已收到的 `content` 片段 |
| `done` | 流正常结束（**最后一条**） | `dialog_id`: string（即新建的 `question.id`） | 标记本轮结束；保存 `dialog_id` 以备「重修」功能使用 |

> **顺序保证**：`session_meta`（如有）→ 多次 `reasoning` 和/或 `content` 交错 → 单条 `done`。出现 `error` 后流即结束（不会再有 `done`）。
>
> **非编程问题**：服务端会预先做分类，若被判断为非编程问题，将仅返回一条固定文案的 `content`（"抱歉，我是专门解答编程和技术问题的助教……"）随后 `done`。

#### SSE 事件示例

```
data: {"type": "session_meta", "session_id": "9c93...", "title": "Python 参数解包"}

data: {"type": "content", "data": "在 Python 中，"}

data: {"type": "content", "data": "`*args` 用于接收任意数量的位置参数..."}

data: {"type": "done", "dialog_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6"}
```

#### 前端实现要点

1. 使用 `fetch` + `ReadableStream` 解析 SSE（**不要**使用 `EventSource`，因为 `POST` + 自定义 Header 它不支持）。
2. 按 `\n\n` 分包，每包去掉 `data: ` 前缀后 `JSON.parse`。
3. 维护一个 `currentDialogId`：收到 `done` 时保存；下次「重修」按钮即用此 ID 作为 `dialog_id` 重新发起请求。
4. 收到 `error` 应中止流并提示重试，已渲染的 `content` 不必清空。
5. 中断（用户主动 abort）时无需额外通知服务端 —— 后端会把已生成内容入库并追加「[回答已被用户中断]」。

---

## 七、问答记录与用量

### 7.1 获取会话问答历史

- **GET** `/api/v1/questions`
- **鉴权**：`student+`
- **Query**

  | 字段 | 类型 | 必填 | 默认 | 约束 | 说明 |
  |---|---|---|---|---|---|
  | `session_id` | string | ✅ | - | - | 目标会话 ID |
  | `limit` | int | - | 50 | 1-200 | 分页大小 |
  | `offset` | int | - | 0 | ≥0 | 偏移 |

- **响应 `data` 结构**：`QuestionOut[]`，按 `created_at` **正序**（聊天上下文阅读顺序）

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `id` | uuid | 问答记录 ID（即 SSE 的 `dialog_id`） |
  | `question` | string | 学生原始提问 |
  | `answer` | string | 模型最终回答；若开启思考链会以 `<think>...</think>` 包裹思考片段在最前部 |
  | `is_programming` | bool | null | 分类结果（非编程问题为 `false`，回答固定文案） |
  | `model` | string | null | 实际使用的模型 ID |
  | `tokens` | int | null | 本轮消耗 token 总数 |
  | `created_at` | datetime | 记录时间 |

  > `is_deleted=true` 的记录已被服务端过滤，无需前端再处理。

- **响应示例**

  ```json
  {
    "code": 0,
    "message": "ok",
    "data": [
      {
        "id": "3fa85f64-...",
        "question": "Python 装饰器是什么？",
        "answer": "装饰器是一种...",
        "is_programming": true,
        "model": "gpt-5-mini",
        "tokens": 1280,
        "created_at": "2026-05-23T01:11:05+00:00"
      }
    ]
  }
  ```

- **失败示例**：`{"code": 1, "message": "会话不存在或无权访问", "data": null}`

---

### 7.2 获取本人模型用量记录

- **GET** `/api/v1/usage`
- **鉴权**：`student+`
- **Query**

  | 字段 | 类型 | 必填 | 默认 | 约束 |
  |---|---|---|---|---|
  | `limit` | int | - | 50 | 1-200 |
  | `offset` | int | - | 0 | ≥0 |

- **响应 `data` 结构**：`UsageRecordOut[]`（按 `created_at` 倒序）

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `id` | uuid | 问答记录 ID |
  | `session_id` | string | null | 所属会话 |
  | `model_id` | string | null | 模型 ID |
  | `tokens` | int | null | 消耗 token |
  | `created_at` | datetime | 记录时间 |

---

## 八、教师端 - 学生与班级

### 8.1 获取学生列表

- **GET** `/api/v1/analysis/students`
- **鉴权**：`teacher+`
- **Query**

  | 字段 | 类型 | 必填 | 默认 | 约束 | 说明 |
  |---|---|---|---|---|---|
  | `limit` | int | - | 20 | 1-100 | 分页大小 |
  | `offset` | int | - | 0 | ≥0 | 偏移 |
  | `class_code` | string | - | null | - | 按班级过滤（学号前缀派生） |

- **响应 `data` 结构**：`StudentOut[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `user_id` | string | 学生 ID |
  | `created_at` | datetime | 注册时间 |

---

### 8.2 获取班级编码列表

- **GET** `/api/v1/analysis/classes`
- **鉴权**：`teacher+`
- **响应 `data` 结构**：`ClassCodeOut[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `class_code` | string | 班级编码（由 `student_no` 解析） |

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": [{"class_code": "240101"}, {"class_code": "240102"}]}
  ```

---

## 九、教师端 - 学习分析

### 9.1 获取每日学习分析

- **GET** `/api/v1/analysis/daily`
- **鉴权**：`teacher+`
- **Query**

  | 字段 | 类型 | 必填 | 默认 | 说明 |
  |---|---|---|---|---|
  | `target_user_id` | string | ✅ | - | 目标学生 ID |
  | `start_date` | string | - | 当天 | `YYYY-MM-DD` |
  | `end_date` | string | - | 当天 | `YYYY-MM-DD` |

- **响应 `data` 结构**：`DailyAnalysisSummaryOut[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `user_id` | string | 学生 ID |
  | `date` | string | `YYYY-MM-DD` |
  | `analysis_text` | string | 自然语言分析 |
  | `analysis_json` | object | null | 见下表 |
  | `model_usage` | array | 当日模型调用次数 |
  | `model_usage[].model_id` | string | 模型 ID |
  | `model_usage[].request_count` | int | 调用次数 |

  `analysis_json` 结构：

  | 字段 | 类型 | 取值 | 说明 |
  |---|---|---|---|
  | `initiative` | string | `high`/`medium`/`low` | 学习主动性 |
  | `depth` | string | `high`/`medium`/`low` | 提问深度 |
  | `topic` | string | - | 当日主要编程主题 |

- **响应示例**

  ```json
  {
    "code": 0,
    "message": "ok",
    "data": [
      {
        "user_id": "2024010101",
        "date": "2026-05-23",
        "analysis_text": "学生今日围绕 Python 装饰器进行了多轮深入提问...",
        "analysis_json": {"initiative": "high", "depth": "medium", "topic": "Python 装饰器"},
        "model_usage": [{"model_id": "gpt-5-mini", "request_count": 7}]
      }
    ]
  }
  ```

---

### 9.2 生成综合学习报告

- **POST** `/api/v1/analysis/report`
- **鉴权**：`teacher+`
- **Query**

  | 字段 | 类型 | 必填 | 默认 | 说明 |
  |---|---|---|---|---|
  | `force` | bool | - | `false` | 强制重新生成（忽略缓存） |

- **请求体**

  | 字段 | 类型 | 必填 | 说明 |
  |---|---|---|---|
  | `target_user_id` | string | ✅ | 目标学生 ID |

- **响应 `data` 结构**：`ReportOut`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `report_text` | string | 完整学习报告文本 |
  | `total_score` | int | null | 综合评估分（0-100） |
  | `profile` | object | null | 各能力维度得分（key 为维度名，value 为数值） |
  | `strengths` | string[] | 优势点列表 |
  | `weaknesses` | string[] | 薄弱点列表 |
  | `suggestions` | string[] | 学习建议列表 |

  > 报告默认取最近 `max_report_days`（30）天的 `daily_analysis` 数据。指定时间段无数据时返回业务失败：`{"code": 1, "message": "指定时间范围内暂无分析数据"}`。

- **响应示例**

  ```json
  {
    "code": 0,
    "message": "ok",
    "data": {
      "report_text": "该生近 30 天累计提问 142 次，主要聚焦 Python 与算法...",
      "total_score": 82,
      "profile": {"基础语法": 90, "算法思维": 76, "工程实践": 70},
      "strengths": ["对装饰器/迭代器掌握扎实", "主动提问意愿强"],
      "weaknesses": ["对异步编程理解不足"],
      "suggestions": ["建议系统学习 asyncio", "增加项目实战练习"]
    }
  }
  ```

---

## 十、教师端 - 行为统计

> 以下接口均为 `teacher+` 鉴权；多数接收 `start_date` / `end_date`（`YYYY-MM-DD`）。

### 10.1 最近活跃学生用量

- **GET** `/api/v1/analysis/recent-usage`
- **Query**：`limit` (int, 默认 10, 1-50) - 取最近 N 个活跃学生
- **响应 `data` 结构**：`RecentModelUsageOut[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `user_id` | string | 学生 ID |
  | `date` | string | 日期 |
  | `model_id` | string | 模型 ID |
  | `request_count` | int | 调用次数 |
  | `prompt_tokens` | int | 提示 token |
  | `completion_tokens` | int | 输出 token |
  | `total_tokens` | int | 总 token |
  | `total_latency_ms` | int | 累计延迟 |
  | `error_count` | int | 失败次数 |

### 10.2 模型使用趋势图

- **GET** `/api/v1/analysis/usage/chart`
- **Query**：`start_date` ✅，`end_date` ✅
- **响应 `data` 结构**：`ModelUsageChartPoint[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `date` | string | 日期 |
  | `model_id` | string | 模型 ID |
  | `request_count` | int | 当日该模型调用次数 |
  | `total_tokens` | int | 当日该模型 token 总量 |

### 10.3 模型使用排行（含同期对比）

- **GET** `/api/v1/analysis/usage/rank`
- **Query**：`start_date` ✅，`end_date` ✅，`period` （`day`/`week`/`month`，默认 `day`）
- **响应 `data` 结构**：`ModelUsageRankItem[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `model_id` | string | 模型 ID |
  | `request_count` | int | 调用次数 |
  | `total_tokens` | int | token 总数 |
  | `delta_request_count` | int | 对比上一周期的调用差 |
  | `delta_total_tokens` | int | 对比上一周期的 token 差 |

### 10.4 活跃用户曲线

- **GET** `/api/v1/analysis/usage/active`
- **Query**：`start_date` ✅，`end_date` ✅，`period`（`day`/`week`/`month`，默认 `day`）
- **响应 `data` 结构**：`ActiveUserPoint[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `period` | string | 时段标识（如 `2026-05-23` / `2026-W21` / `2026-05`） |
  | `active_users` | int | 该时段活跃学生数 |

### 10.5 模型错误率趋势

- **GET** `/api/v1/analysis/usage/error-trend`
- **Query**：`start_date` ✅，`end_date` ✅
- **响应 `data` 结构**：`ModelErrorTrendPoint[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `date` | string | 日期 |
  | `model_id` | string | 模型 ID |
  | `error_count` | int | 错误次数 |
  | `request_count` | int | 总调用 |
  | `error_rate` | float | 错误率（0-1） |

### 10.6 模型延迟趋势

- **GET** `/api/v1/analysis/usage/latency-trend`
- **Query**：`start_date` ✅，`end_date` ✅
- **响应 `data` 结构**：`ModelLatencyTrendPoint[]`

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `date` | string | 日期 |
  | `model_id` | string | 模型 ID |
  | `total_latency_ms` | int | 累计耗时 |
  | `request_count` | int | 调用次数 |
  | `avg_latency_ms` | float | 平均耗时（毫秒） |

---

## 十一、教师端 - 批量导出报告

> 异步任务模式。前端流程：**创建任务 → 轮询/列表查询状态 → 下载结果文件**。

### 11.1 创建导出任务

- **POST** `/api/v1/analysis/report/export/jobs`
- **鉴权**：`teacher+`
- **请求体**

  | 字段 | 类型 | 必填 | 默认 | 说明 |
  |---|---|---|---|---|
  | `class_code` | string | - | null | 按班级筛选学生（null = 全部） |
  | `include_text_evaluation` | bool | - | `false` | Excel 中是否包含「文字评价」列（耗时显著增加） |
  | `course_name` | string | - | null | 报表表头课程名 |
  | `teacher_name` | string | - | 取当前用户 `real_name` | 报表表头教师名 |
  | `school_name` | string | - | `"河北农业大学"` | 报表表头学校名 |

- **响应 `data` 结构**

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `job_id` | string | 新建任务 ID |

- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": {"job_id": "3fa85f64-..."}}
  ```

---

### 11.2 列出本人导出任务

- **GET** `/api/v1/analysis/report/export/jobs`
- **鉴权**：`teacher+`
- **响应 `data` 结构**：`ExportSummaryReportJobOut[]`（按 `created_at` 倒序）

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `job_id` | string | 任务 ID |
  | `status` | string | `pending` / `running` / `completed` / `completed_with_errors` / `failed` |
  | `total_count` | int | 学生总数 |
  | `completed_count` | int | 已完成数 |
  | `failed_count` | int | 失败数 |
  | `progress` | float | 进度（0-1，`completed_count / total_count`） |
  | `result_ready` | bool | 结果文件是否可下载（只有 `completed` / `completed_with_errors` 且文件存在为 `true`） |
  | `class_code` | string | null | 筛选班级 |
  | `school_name` | string | null | 报表表头 |
  | `course_name` | string | null | 报表表头 |
  | `teacher_name` | string | null | 报表表头 |
  | `created_at` | datetime | 创建时间 |
  | `updated_at` | datetime | 更新时间 |

---

### 11.3 查询单个任务状态

- **GET** `/api/v1/analysis/report/export/jobs/{job_id}`
- **鉴权**：`teacher+`
- **响应**：同 11.2 单条
- **失败**：`{"code": 1, "message": "任务不存在", "data": null}`

> 前端轮询建议：状态为 `pending` / `running` 时每 3-5 秒拉一次；变为 `completed*` 或 `failed` 即停止。

---

### 11.4 下载结果文件

- **GET** `/api/v1/analysis/report/export/jobs/{job_id}/result`
- **鉴权**：`teacher+`
- **响应**：
  - **成功**：直接返回 `.xlsx` 二进制流（`Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`），并附 `Content-Disposition` 文件名。
  - **失败**（JSON 格式）：`{"code": 1, "message": "结果尚未生成" | "结果文件不存在", "data": null}`

> 前端可使用 `<a href download>` 或 `fetch + blob` 触发下载；务必先用 11.2 / 11.3 判断 `result_ready === true` 后再下载。

---

### 11.5 删除导出任务

- **DELETE** `/api/v1/analysis/report/export/jobs/{job_id}`
- **鉴权**：`teacher+`
- **响应示例**：`{"code": 0, "message": "ok", "data": "Job deleted"}`
- **失败示例**：
  - `{"code": 1, "message": "任务不存在", "data": null}`
  - `{"code": 1, "message": "任务执行中，暂时无法删除", "data": null}`（`status=running` 时不允许删除）

---

## 十二、管理员

### 12.1 立即触发指定学生的每日分析

- **POST** `/api/v1/analysis/daily/run`
- **鉴权**：`admin`
- **请求体**

  | 字段 | 类型 | 必填 | 默认 | 说明 |
  |---|---|---|---|---|
  | `target_user_id` | string | ✅ | - | 目标学生 ID |
  | `date` | string | - | 当天 | `YYYY-MM-DD` |

- **响应 `data` 结构**

  | 字段 | 类型 | 说明 |
  |---|---|---|
  | `processed` | bool | 是否成功生成分析（`false` 表示无数据 / 已存在等） |
  | `date` | string | 实际处理日期 |
  | `analysis_text` | string | null | 生成的分析文本（`processed=false` 时为 null） |
  | `analysis_json` | object | null | 见 9.1 `analysis_json` |
  | `created_at` | datetime | null | 入库时间 |
  | `...` | - | 其他后端返回的元数据字段 |

---

## 十三、系统

### 13.1 健康检查

- **GET** `/api/v1/health`
- **鉴权**：无
- **响应示例**

  ```json
  {"code": 0, "message": "ok", "data": {"status": "ok"}}
  ```

---

## 附录 A：前端请求封装建议（伪代码）

```ts
// axios 拦截器示例
axios.interceptors.request.use(cfg => {
  const userId = localStorage.getItem("user_id");
  if (userId) cfg.headers.Authorization = `Bearer ${userId}`;
  return cfg;
});

axios.interceptors.response.use(resp => {
  // 仅适用于 JSON 接口；流式接口请走原生 fetch
  const { code, message, data } = resp.data;
  if (code === 0) return data;
  throw new BusinessError(message);
}, err => {
  if (err.response?.status === 401) location.href = "/login";
  if (err.response?.status === 429) toast("请求过于频繁，请稍后再试");
  throw err;
});
```

## 附录 B：流式 `/chat` 解析示例

```ts
async function streamChat(body: ChatRequest, onEvent: (e: SSEEvent) => void) {
  const resp = await fetch("/api/v1/chat", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${userId}`,
    },
    body: JSON.stringify(body),
  });
  if (!resp.ok || !resp.body) throw new Error("stream failed");

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const raw = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 2);
      if (!raw.startsWith("data:")) continue;
      const payload = JSON.parse(raw.slice(5).trim());
      onEvent(payload);
      if (payload.type === "done" || payload.type === "error") return;
    }
  }
}
```

## 附录 C：常见错误 message 对照

| message | 含义 | 触发接口 |
|---|---|---|
| `账号已存在` | 注册的 `user_id`/`student_no` 已被占用 | 3.1 / 3.2 |
| `模型不可用` | `model_id` 不在 `/models` 返回列表中 | 6.1 |
| `会话不存在或无权访问` | session 不属于当前用户或已被删除 | 5.3 / 5.4 / 6.1 / 7.1 |
| `没有可删除的会话` | 批量删除范围内无会话 | 5.2 |
| `指定时间范围内暂无分析数据` | 时间段内无 `daily_analysis` 记录 | 9.2 |
| `任务不存在` | 导出任务 ID 不属于当前用户 | 11.3 / 11.5 |
| `任务执行中，暂时无法删除` | 试图删除 `running` 状态任务 | 11.5 |
| `结果尚未生成` / `结果文件不存在` | 下载时任务未完成或文件缺失 | 11.4 |
| `请求过于频繁，请稍后再试` | 命中 `/chat` 限流（HTTP 429） | 6.1 |
| `缺少身份凭证` | 请求未带任何身份字段（HTTP 401） | 所有需鉴权接口 |
| `用户不存在` | 携带的 `user_id` 在 DB 中查不到（HTTP 403） | 所有需鉴权接口 |
| `权限不足` | 角色权重不够（HTTP 403） | 教师/管理员接口 |

---

_文档版本：v1.0（基于代码 commit `6d78887`）_
