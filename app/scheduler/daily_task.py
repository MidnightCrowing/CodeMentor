"""
scheduler/daily_task.py
========================
离线定时任务模块。

职责：
- 使用 APScheduler 在凌晨 daily_analysis_hour 点（默认 3 点）触发每日学习分析
- 调用 analysis_service.run_daily_analysis() 完成数据处理

⚠️ 重要：必须确保单实例运行！
    - Uvicorn 启动时使用 workers=1
    - 或者在多进程环境使用额外的互斥锁
    - 当前方案：依赖 APScheduler 运行在 FastAPI 主进程中，天然单实例

使用方式：
    在 main.py 启动时调用 start_scheduler()
    在 main.py 关闭时调用 stop_scheduler()
"""

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import analysis_service

logger = logging.getLogger(__name__)

# ── 调度器单例 ────────────────────────────────────────────────
_scheduler = AsyncIOScheduler()


async def _daily_analysis_job() -> None:
    """
    定时任务实体函数。
    每次执行时自动创建独立的数据库会话，保证事务隔离。
    """
    today = date.today().isoformat()
    logger.info(f"[定时任务] 开始执行每日分析：{today}")

    async with AsyncSessionLocal() as db:
        try:
            result = await analysis_service.run_daily_analysis(db=db, date_str=today)
            await db.commit()
            logger.info(
                f"[定时任务] 每日分析完成：处理 {result['processed_users']} 人，"
                f"跳过 {result['skipped']} 人"
            )
        except Exception as e:
            await db.rollback()
            logger.error(f"[定时任务] 每日分析失败：{e}", exc_info=True)


def start_scheduler() -> None:
    """
    启动调度器。在 FastAPI lifespan 的 startup 事件中调用。
    注册每日凌晨 daily_analysis_hour 点执行的任务。
    """
    hour = settings.daily_analysis_hour
    _scheduler.add_job(
        _daily_analysis_job,
        trigger=CronTrigger(hour=hour, minute=0),
        id="daily_analysis",
        replace_existing=True,  # 防止重复注册
        misfire_grace_time=3600,  # 如果错过触发时间，1 小时内补运行
    )
    _scheduler.start()
    logger.info(f"[定时任务] APScheduler 已启动，每日 {hour:02d}:00 执行分析")


def stop_scheduler() -> None:
    """
    停止调度器。在 FastAPI lifespan 的 shutdown 事件中调用。
    """
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
        logger.info("[定时任务] APScheduler 已停止")
