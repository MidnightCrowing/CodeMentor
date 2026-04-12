"""
定时任务模块。

- 每日学习分析
- 数据库备份
- Batch 结果轮询
- 导出任务后台处理
"""

import asyncio
import logging
from datetime import timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, text

from app.core.config import CHINA_TZ, settings
from app.core.database import AsyncSessionLocal
from app.models.models import Question
from app.services import analysis_service, db_service, report_export_service

logger = logging.getLogger(__name__)

_scheduler = AsyncIOScheduler()
_tasks: set[asyncio.Task] = set()
_daily_lock = asyncio.Lock()
_batch_lock = asyncio.Lock()
_export_trigger = asyncio.Event()

_scheduler_lock_fd = None
_is_master: bool | None = None

def acquire_master_lock() -> bool:
    """尝试获取文件锁，确保多进程下只有 1 个实例运行调度器和初始化流程。"""
    global _scheduler_lock_fd, _is_master
    if _is_master is not None:
        return _is_master

    import os
    try:
        if os.name == 'nt':
            import msvcrt
            lock_file = open("scheduler.lock", "w")
            msvcrt.locking(lock_file.fileno(), msvcrt.LK_NBLCK, 1)
            _scheduler_lock_fd = lock_file
        else:
            import fcntl
            lock_file = open("/tmp/scheduler.lock", "w")
            fcntl.lockf(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
            _scheduler_lock_fd = lock_file
        _is_master = True
    except Exception:
        _is_master = False
        
    return _is_master


async def _database_backup_job() -> None:
    """凌晨 4 点执行数据库备份，并清理旧备份。"""
    logger.info("[定时任务] 开始执行数据库备份")
    try:
        path = db_service.backup_database()
        if path:
            count = db_service.cleanup_old_backups(days=10)
            logger.info("[定时任务] 数据库备份完成，文件=%s，清理旧备份=%s 个", path, count)
    except Exception as exc:
        logger.error("[定时任务] 数据库备份或清理失败: %s", exc, exc_info=True)


def trigger_export_worker() -> None:
    """唤醒导出后台处理线程。"""
    _export_trigger.set()


async def _export_worker_loop() -> None:
    """长期运行的导出任务后台循环。"""
    logger.info("[任务队列] 导出后台工作线程已启动")
    while True:
        try:
            try:
                await asyncio.wait_for(_export_trigger.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass

            _export_trigger.clear()
            await report_export_service.process_all_pending_jobs()
        except Exception as exc:
            logger.error("[任务队列] 导出工作线程处理异常: %s", exc, exc_info=True)
            await asyncio.sleep(5)


def _track_task(task: asyncio.Task) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _spawn(coro) -> None:
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        return
    _track_task(task)


async def _daily_analysis_job() -> None:
    """执行每日分析、数据清理和导出清理。"""
    from datetime import datetime

    today = datetime.now(CHINA_TZ).date().isoformat()
    logger.info("[定时任务] 开始执行每日分析，日期=%s", today)

    async with AsyncSessionLocal() as db:
        try:
            if settings.batch_api_key:
                result = await analysis_service.submit_daily_analysis_batch(db=db, date_str=today)
                if result.get("submitted", 0) > 0:
                    logger.info(
                        "[定时任务] 已提交批量分析任务，日期=%s，提交请求数=%s",
                        today,
                        result.get("submitted", 0),
                    )
                    resume_batch_poll()
            else:
                result = await analysis_service.run_daily_analysis(db=db, date_str=today)

            if settings.delete_history_days > 0:
                cutoff_date = datetime.now(CHINA_TZ) - timedelta(days=settings.delete_history_days)
                stmt = delete(Question).where(Question.created_at < cutoff_date)
                res = await db.execute(stmt)
                logger.info(
                    "[定时任务] 已物理清理过期对话，删除=%s 条，保留天数=%s",
                    res.rowcount,
                    settings.delete_history_days,
                )

            if settings.db_cleanup_size_gb > 0:
                try:
                    size_res = await db.execute(
                        text("SELECT pg_database_size(current_database()) / 1024.0 / 1024.0 / 1024.0")
                    )
                    db_size_gb = size_res.scalar()
                    if db_size_gb and db_size_gb > settings.db_cleanup_size_gb:
                        logger.warning(
                            "[定时任务告警] 数据库体积过大，当前=%.2fGB，阈值=%.2fGB",
                            db_size_gb,
                            settings.db_cleanup_size_gb,
                        )
                except Exception as exc:
                    logger.debug("[定时任务] 数据库容量探测失败: %s", exc)

            try:
                count = report_export_service.cleanup_old_exports(days=7)
                db_count = await report_export_service.cleanup_old_export_jobs(db, days=7)
                if count > 0 or db_count > 0:
                    logger.info(
                        "[定时任务] 已清理过期导出任务，文件=%s 个，数据库记录=%s 条",
                        count,
                        db_count,
                    )
            except Exception as exc:
                logger.error("[定时任务] 清理导出记录失败: %s", exc, exc_info=True)

            await db.commit()
            if settings.batch_api_key:
                logger.info("[定时任务] 每日分析批量任务提交完成")
            else:
                logger.info(
                    "[定时任务] 每日分析完成，处理用户=%s，跳过=%s",
                    result["processed_users"],
                    result["skipped"],
                )
        except Exception as exc:
            await db.rollback()
            logger.error("[定时任务] 每日分析失败: %s", exc, exc_info=True)


async def _batch_poll_job() -> None:
    """轮询 batch 任务状态，并在完成后回写结果。"""
    if not settings.batch_api_key:
        return

    async with AsyncSessionLocal() as db:
        try:
            jobs = await analysis_service.list_pending_batch_jobs(db=db)
            if not jobs:
                # 没有待处理任务时暂停轮询，减少空转和日志噪音。
                pause_batch_poll()
                return

            logger.info("[定时任务] 开始轮询 Batch 任务，待处理数量=%s", len(jobs))

            for job in jobs:
                await analysis_service.process_batch_job(db=db, job=job)

            await db.commit()
        except Exception as exc:
            await db.rollback()
            logger.error("[定时任务] Batch 轮询失败: %s", exc, exc_info=True)


def pause_batch_poll() -> None:
    """暂停 Batch 轮询任务。"""
    try:
        _scheduler.pause_job("batch_poll")
        logger.debug("[定时任务] 当前没有活跃 Batch 任务，轮询已暂停")
    except Exception:
        pass


def resume_batch_poll() -> None:
    """恢复 Batch 轮询任务。"""
    try:
        _scheduler.resume_job("batch_poll")
        logger.info("[定时任务] 已恢复 Batch 结果轮询")
    except Exception:
        pass


def _schedule_daily() -> None:
    async def _runner() -> None:
        async with _daily_lock:
            await _daily_analysis_job()

    _spawn(_runner())


def _schedule_batch() -> None:
    async def _runner() -> None:
        async with _batch_lock:
            await _batch_poll_job()

    _spawn(_runner())


def start_scheduler() -> None:
    """启动调度器。"""
    if _scheduler.running:
        logger.debug("[定时任务] 调度器已在运行，跳过重复启动")
        return

    if not acquire_master_lock():
        return

    hour = settings.daily_analysis_hour
    _scheduler.add_job(
        _schedule_daily,
        trigger=CronTrigger(hour=hour, minute=0, timezone=CHINA_TZ),
        id="daily_analysis",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _database_backup_job,
        trigger=CronTrigger(hour=4, minute=0, timezone=CHINA_TZ),
        id="database_backup",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    _scheduler.add_job(
        _schedule_batch,
        trigger="interval",
        minutes=settings.batch_poll_minutes,
        id="batch_poll",
        replace_existing=True,
        misfire_grace_time=60,
    )

    try:
        _scheduler.start()
        logger.info("[定时任务] APScheduler 已启动，每日分析时间=%02d:00", hour)
        _track_task(asyncio.create_task(_export_worker_loop()))
    except Exception as exc:
        logger.error("[定时任务] 启动调度器失败: %s", exc, exc_info=True)


async def stop_scheduler() -> None:
    """停止调度器并清理挂起任务。"""
    if _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("[定时任务] APScheduler 已停止")
        except Exception as exc:
            logger.error("[定时任务] 停止调度器异常: %s", exc, exc_info=True)

    if _tasks:
        living_tasks = [task for task in _tasks if not task.done()]
        if living_tasks:
            logger.info("[定时任务] 正在取消 %s 个运行中的异步任务", len(living_tasks))
            for task in living_tasks:
                task.cancel()

            try:
                await asyncio.wait_for(
                    asyncio.gather(*living_tasks, return_exceptions=True),
                    timeout=5.0,
                )
                logger.info("[定时任务] 所有子任务已清理完成")
            except asyncio.TimeoutError:
                logger.warning("[定时任务] 等待任务停止超时，已跳过")
            except Exception as exc:
                logger.debug("[定时任务] 清理任务时出现非致命异常: %s", exc)

        _tasks.clear()
