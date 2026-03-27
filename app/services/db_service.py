"""
services/db_service.py
=======================
数据库管理业务逻辑：备份与清理。
"""

import os
import subprocess
import logging
from datetime import datetime, timedelta
from pathlib import Path
from app.core.config import settings

logger = logging.getLogger(__name__)

def backup_database() -> str | None:
    """
    导出当前 PostgreSQL 数据库全量备份。
    
    Returns:
        备份文件路径（成功）或 None（失败）
    """
    backup_dir = Path("database_backups")
    backup_dir.mkdir(parents=True, exist_ok=True)
    
    from app.core.config import CHINA_TZ
    timestamp = datetime.now(CHINA_TZ).strftime("%Y%m%d_%H%M%S")
    db_name = "codementor"
    output_file = backup_dir / f"backup_{db_name}_{timestamp}.sql"
    
    # 构建 pg_dump 命令 (注意：此命令需要在环境中能直接执行 pg_dump)
    # 在 Docker 环境下，我们不需要 docker exec，直接执行即可（因为 app 在 webapp 容器内运行）
    try:
        # 通过环境变量 PGPASSWORD 传递密码（避免交互）
        # 这里动态从 DATABASE_URL 提取密码可能复杂，我们假设 PGPASSWORD 已经在系统环境中（或我们在 envfile 定义了）
        env = os.environ.copy()
        
        # 尝试从 URL 中解析密码并注入环境变量
        if "postgresql+asyncpg" in settings.database_url:
            password = settings.database_url.split("//")[1].split("@")[0].split(":")[1]
            host = settings.database_url.split("@")[1].split(":")[0]
            env["PGPASSWORD"] = password
            env["PGHOST"] = host
            env["PGPORT"] = "5432"
            env["PGUSER"] = "postgres"
        
        logger.info(f"[DB备份] 正在开始备份至: {output_file}...")
        
        # 执行 pg_dump
        process = subprocess.run(
            ["pg_dump", "-U", "postgres", "-d", db_name, "-f", str(output_file)],
            env=env,
            capture_output=True,
            text=True
        )
        
        if process.returncode == 0:
            logger.info(f"✅ [DB备份] 备份成功！文件大小: {os.path.getsize(output_file)} bytes")
            return str(output_file)
        else:
            logger.error(f"❌ [DB备份] 备份失败: {process.stderr}")
            return None
            
    except Exception as e:
        logger.error(f"❌ [DB备份] 执行异常: {e}")
        return None

def cleanup_old_backups(days: int = 10) -> int:
    """
    清理指定天数之前的备份文件。
    """
    backup_dir = Path("database_backups")
    if not backup_dir.exists():
        return 0
        
    cutoff_time = datetime.now() - timedelta(days=days)
    count = 0
    
    for f in backup_dir.glob("*.sql"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime)
            if mtime < cutoff_time:
                f.unlink()
                count += 1
        except Exception as e:
            logger.debug(f"[DB清理] 忽略无法处理的文件 {f}: {e}")
            
    if count > 0:
        logger.info(f"🧹 [DB清理] 已清理 {count} 个 {days} 天前的旧备份文件")
    return count
