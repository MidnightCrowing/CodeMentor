import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import settings

def setup_logging():
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    # 格式化器
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s"
    )

    # 1. 错误日志 (error.log)
    error_handler = RotatingFileHandler(
        log_dir / "error.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)

    # 2. 应用日志 (app.log)
    app_handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(fmt)

    # 3. 控制台输出 (方便开发调试)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)

    # 配置根日志器
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    
    # 清理已有 handler，避免重复
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(error_handler)
    root_logger.addHandler(app_handler)
    root_logger.addHandler(console_handler)

    # 4. 访问日志 (access.log) - 为 uvicorn.access 提供独立文件
    access_handler = RotatingFileHandler(
        log_dir / "access.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))
    
    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    if uvicorn_access_logger.hasHandlers():
        uvicorn_access_logger.handlers.clear()
    uvicorn_access_logger.addHandler(access_handler)
    uvicorn_access_logger.propagate = False  # 不要将 access 日志同步输出到 app.log 进而污染

    # 可选：配置 sqlalchemy 日志以便记录慢SQL或报错
    sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
    sqlalchemy_logger.setLevel(logging.WARNING)
    sqlalchemy_logger.addHandler(error_handler)
    sqlalchemy_logger.addHandler(app_handler)

    logging.getLogger(__name__).info("日志系统初始化完成。")
