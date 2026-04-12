# 第一阶段：编译环境 (可选但建议，这里采用单阶段简易化)
FROM python:3.13-slim-bookworm

# 设置工作目录
WORKDIR /app

# 设置环境变量：不生成 .pyc, 不缓冲输出, 设置 PYTHONPATH
ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1
ENV PYTHONPATH /app

# 安装必要的系统依赖（针对 pydantic, asyncpg 等可能涉及编译的库）
# 针对国内环境，将 Debian 源替换为阿里云加速
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    ca-certificates \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# 安装 PostgreSQL 官方源以获取 pg_dump 18.x
RUN curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql.gpg && \
    echo "deb [signed-by=/usr/share/keyrings/postgresql.gpg] http://apt.postgresql.org/pub/repos/apt bookworm-pgdg main" > /etc/apt/sources.list.d/pgdg.list && \
    apt-get update && apt-get install -y postgresql-client-18 && \
    rm -rf /var/lib/apt/lists/*

# 安装 Python 依赖（配置清华、阿里、腾讯等多重备用镜像）
COPY requirements.txt .
RUN pip config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple && \
    pip config set global.extra-index-url "https://pypi.org/simple https://mirrors.aliyun.com/pypi/simple https://mirrors.bfsu.edu.cn/pypi/web/simple https://mirrors.cloud.tencent.com/pypi/simple https://repo.huaweicloud.com/repository/pypi/simple" && \
    pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 复制代码
COPY . .

# 创建持久化目录
RUN mkdir -p logs exports database_backups

# 暴露端口（与 config.yaml 默认端口保持一致）
EXPOSE 8000

# 启动脚本：自动执行数据库同步并使用 Gunicorn 启动服务
# TODO(性能调优): 当前服务器为 2 核，设为 5 个 worker (2*2+1)。未来升级 8 核请改为 17，16 核请改为 33
CMD alembic upgrade head && gunicorn app.main:app -w 5 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000
