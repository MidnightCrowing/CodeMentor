# API 设计规范

## 基础规范

- **Base URL**: `/api/v1`

## 统一返回格式

所有非流式 API 接口均需遵循以下标准的 JSON 格式返回。

### 成功响应
```json
{
  "code": 0,
  "message": "ok",
  "data": {
    // 具体的返回数据
  }
}
```

### 错误响应
```json
{
  "code": 1,
  "message": "错误信息描述",
  "data": null
}
```

## 接口列表

### 1. 聊天对话 (Streaming)
- **POST** `/chat`
- **参数**:
  - `user_id` (str, 必选): 用户唯一标识。
  - `session_id` (str, 可选): 会话 ID。首次创建新会话不传即可，服务端将在流最后返回新的 ID。
  - `message` (str, 必选): 用户输入的内容。
  - `model_id` (str, 可选): 指定对话模型 ID。如果不传，则使用系统默认模型。
  - `enable_thinking` (bool, 可选，默认为 true): 是否开启模型的深度思考功能。

### 2. 获取会话列表
- **GET** `/sessions`
- **参数**:
  - `user_id` (str, 必选): 查询目标的用户 ID。
  - `limit` (int, 可选): 每页返回条数，默认返回 20 条。
  - `offset` (int, 可选): 分页偏移量，默认 0。
- **返回数据 (`data` 结构)**:
  - 数组类型，每个元素包含 `id`, `title`, `created_at` 等信息。

### 2.5 删除会话记录
- **DELETE** `/sessions/{session_id}`
- **参数**:
  - `session_id` (str, 路径参数): 要被移除的会话标识。
  - `user_id` (str, 必填 Query): 用户标示，避免越权。
- **返回数据 (`data` 结构)**:
  - 字符串 `提示操作成功` 即可。

### 2. 获取可用模型列表
- **GET** `/chat/models`
- **返回数据 (`data` 结构)**:
  - 数组类型，每个元素包含:
    - `id` (str): 模型 ID，用于请求 `/chat` 接口时传递。
    - `name` (str): 推荐的前端显示名称。
    - `support_thinking` (bool): 标识该模型是否支持思维链 (Thinking) 输出。

### 3. 获取历史问答记录
- **GET** `/chat/questions`
- **参数**:
  - `user_id` (str, 必选): 查询目标的用户 ID。
  - `session_id` (str, 必选): 查询目标的会话 ID。
  - `limit` (int, 可选): 每页返回条数，默认返回 50 条。
  - `offset` (int, 可选): 分页偏移量，默认 0。
- **返回数据 (`data` 结构)**:
  - 包含指定会话下多个问答对象数据的数组列表（自动屏蔽 `is_deleted` 被废弃重修的问题，按时间正序排列从上至下）。

### 4. 获取每日分析结果
- **GET** `/analysis/daily`
- **参数**:
  - `user_id` (str, 必选): 查询目标的用户 ID。
  - `start_date` (str, 可选): 起始日期（YYYY-MM-DD），缺省查当日。
  - `end_date` (str, 可选): 结束日期（YYYY-MM-DD），缺省查当日。
- **返回数据 (`data` 结构)**:
  - 数组类型，每个元素包含当天的学习分析等统计项。

### 5. 生成综合学习报告
- **POST** `/analysis/report`
- **参数**:
  - `user_id` (str, 必选): 请求体中提供目标用户 ID。
- **返回数据 (`data` 结构)**:
  - 包含 `report` (str) 字段的综合评估总结报告对象。

### 6. 健康检查
- **GET** `/health`
- **返回数据 (`data` 结构)**:
  - 包含 `status` (str) 字段的心跳检测状态，例如 `{"status": "ok"}`。
