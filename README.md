# CodeMentor

### 目录结构
* `/app` - 核心业务源码及 FastAPI 原生编排逻辑
* `/alembic` - 数据库架构迁移管理脚本
* `/docs` - 项目的额外标准文档与 API 设计约定
* `/logs` - 各类终端应用级日志文件系统位置

### 本地开发调试
```bash
# 启动热重载开发服务器
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# [数据库表结构变更时] 自动比对 models.py 生成迁移文件
alembic revision --autogenerate -m "新增了xx字段"

# [数据库表结构变更时] 让数据库应用上述的变更
alembic upgrade head
```

### 生产环境 Docker 管理
```bash
# 启动所有服务
docker compose up -d

# 停止服务（不删除）
docker compose stop

# 启动已停止服务
docker compose start

# 重启服务
docker compose restart

# 停止并删除容器（不删数据卷）
docker compose down

# 重建镜像并启动
docker compose up -d --build

# 查看日志
docker compose logs -f

# 查看状态
docker compose ps
```

### 数据库安全与运维
*(注：首次在 linux 运行需赋权：`chmod +x scripts/*.sh`)*

```bash
# 1. 自动执行数据库全量导出 (存至 database_backups 目录)
./scripts/backup.sh

# 2. 从指定 SQL 文件恢复数据 (⚠️高危操作，将覆盖现有数据库)
./scripts/restore.sh ./database_backups/你的SQL备份文件名.sql
```
