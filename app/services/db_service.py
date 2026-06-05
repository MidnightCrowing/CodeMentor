"""
数据库管理服务，包含备份与清理逻辑。
"""

import logging
import os
import subprocess
from datetime import timedelta
from pathlib import Path

from app.core.config import settings, CHINA_TZ
from app.core.time_utils import days_ago_biz

logger = logging.getLogger(__name__)


def backup_database() -> str | None:
    """
    导出当前 PostgreSQL 数据库全量备份。

    Returns:
        备份文件路径；失败时返回 `None`。
    """
    backup_dir = Path(settings.backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    from app.core.config import CHINA_TZ

    timestamp = datetime.now(CHINA_TZ).strftime("%Y%m%d_%H%M%S")
    db_name = "codementor"
    output_file = backup_dir / f"backup_{db_name}_{timestamp}.sql"

    try:
        env = os.environ.copy()

        if "postgresql+asyncpg" in settings.database_url:
            password = settings.database_url.split("//")[1].split("@")[0].split(":")[1]
            host = settings.database_url.split("@")[1].split(":")[0]
            env["PGPASSWORD"] = password
            env["PGHOST"] = host
            env["PGPORT"] = "5432"
            env["PGUSER"] = "postgres"

        logger.info("[数据库备份] 开始执行备份，目标文件=%s", output_file)

        process = subprocess.run(
            ["pg_dump", "-U", "postgres", "-d", db_name, "-f", str(output_file)],
            env=env,
            capture_output=True,
            text=True,
        )

        if process.returncode == 0:
            logger.info(
                "[数据库备份] 备份成功，文件大小=%s 字节",
                os.path.getsize(output_file),
            )
            return str(output_file)

        logger.error("[数据库备份] 备份失败，错误输出=%s", process.stderr)
        return None

    except Exception as exc:
        logger.error("[数据库备份] 执行异常: %s", exc, exc_info=True)
        return None


def cleanup_old_backups(days: int = 10) -> int:
    """清理指定天数之前的备份文件。"""
    backup_dir = Path(settings.backup_dir)
    if not backup_dir.exists():
        return 0

    from datetime import datetime
    cutoff_time = days_ago_biz(days)
    count = 0

    for file_path in backup_dir.glob("*.sql"):
        try:
            mtime = datetime.fromtimestamp(file_path.stat().st_mtime, tz=CHINA_TZ)
            if mtime < cutoff_time:
                file_path.unlink()
                count += 1
        except Exception as exc:
            logger.debug("[数据库清理] 忽略无法处理的文件=%s 错误=%s", file_path, exc)

    if count > 0:
        logger.info("[数据库清理] 已清理 %s 个 %s 天前的旧备份文件", count, days)
    return count
