---
name: update-api-doc
description: 修改后端的 API 代码时，如何更新 API 文档
---

## 背景
CodeMentor 项目的后端 API 接口使用了统一的返回格式规范，且相关的接口文档维护在 `docs/api.md`。

## 规范步骤
当你执行任何新增、修改、删除后端 `/api` 接口的操作时，必须同步更新 API 文档。

1. **统一返回格式要求**：新增接口必须遵守该格式：
   - 成功: `{"code": 0, "message": "ok", "data": {...}}`
   - 失败: `{"code": 1, "message": "error message", "data": null}`
2. **定位文档文件**：读取或修改 `e:\Projects\CodeMentor\docs\api.md`。
3. **编写格式**：在文档中准确写出方法类型（GET/POST）、路径、参数（清晰标定是必选还是可选），以及参数的作用。**禁止使用任何表情符号**。
4. **简洁为主**：文档语言必须简洁明了，不要包含废话和过度设计的排版。
