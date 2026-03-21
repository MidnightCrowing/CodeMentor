# CodeMentor

## 目录结构
* `/app` - 核心业务源码及 FastAPI 原生编排逻辑
* `/alembic` - 数据库架构迁移管理脚本
* `/docs` - 项目的额外标准文档与 API 设计约定
* `/logs` - 各类终端应用级日志文件系统位置

## 环境与依赖安装
本机开发推荐使用 Conda 隔离 Python 3.13 运行环境：
```bash
# 创建并激活 Conda 环境
conda create -n CodeMentor python=3.13 -y
conda activate CodeMentor

# 安装相关依赖包
pip install -r requirements.txt
```

请在项目根目录下确保存在 `.env` 文件，内容中至少包含大模型必需的 API Key 以及数据库连接串：
```env
OPENAI_API_KEY=your_api_key_here
DATABASE_URL=postgresql+asyncpg://user:password@localhost/codementor_db
```

## 常用命令

### 1. 开发启动环境
启用内建服务器并带有代码热重载支持：
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. 数据库迁移方案 (Alembic)
此项目涉及 SQLAlchemy 表结构的不断演进。如更新 `models.py`，请执行以下指令应用架构修改至数据库之中：
```bash
# 自动比对结构并生成迁移版本
alembic revision --autogenerate -m "描述您这次变更的内容"

# 将迁移挂载到远端以正式完成更新
alembic upgrade head
```
