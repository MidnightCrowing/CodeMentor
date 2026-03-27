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
    在 main.py 关闭时 await stop_scheduler()
"""

import asyncio
import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy import delete, text
from datetime import timezone, timedelta

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.models import Question
from app.services import analysis_service, report_export_service

logger = logging.getLogger(__name__)

# 调度器单例
_scheduler = AsyncIOScheduler()
_tasks: set[asyncio.Task] = set()
_daily_lock = asyncio.Lock()
_batch_lock = asyncio.Lock()
_export_trigger = asyncio.Event()


def trigger_export_worker() -> None:
    """
    手动设置事件，唤醒后台导出工作线程。
    由 Web API 调用（快速响应）。
    """
    _export_trigger.set()


async def _export_worker_loop() -> None:
    """
    长期运行的导出任务工作线程。
    同时支持 1 分钟周期轮询 + 事件主动唤醒。
    """
    logger.info("[任务队列] 导出后台工作线程已启动")
    while True:
        try:
            # 等待信号，或者每 60 秒强制扫描一次作为保底
            try:
                await asyncio.wait_for(_export_trigger.wait(), timeout=60)
            except asyncio.TimeoutError:
                pass
            
            _export_trigger.clear()
            # 捡起所有 pending 任务开始执行
            await report_export_service.process_all_pending_jobs()
        except Exception as e:
            logger.error(f"[任务队列] 导出工作线程处理异常: {e}", exc_info=True)
            await asyncio.sleep(5)  # 发生异常时稍作等待，防止 CPU 飙升


def _track_task(task: asyncio.Task) -> None:
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


def _spawn(coro) -> None:
    try:
        task = asyncio.create_task(coro)
    except RuntimeError:
        # No running loop (e.g., during interpreter shutdown). Skip spawning.
        return
    _track_task(task)


async def _daily_analysis_job() -> None:
    """
    定时任务实体函数。
    每次执行时自动创建独立的数据库会话，保证事务隔离。
    """
    today = date.today().isoformat()
    logger.info(f"[定时任务] 开始执行每日分析：{today}")

    async with AsyncSessionLocal() as db:
        try:
            if settings.batch_api_key:
                result = await analysis_service.submit_daily_analysis_batch(db=db, date_str=today)
                if result.get("submitted", 0) > 0:
                    logger.info(
                        f"[定时任务] 已提交批量分析任务：{today}，提交 {result.get('submitted', 0)} 条请求"
                    )
                    # 提交了新任务，确保轮询器处于唤醒状态
                    resume_batch_poll()
            else:
                result = await analysis_service.run_daily_analysis(db=db, date_str=today)
            
            # 附带执行过期数据物理清理
            if settings.delete_history_days > 0:
                from app.models.models import _now_utc
                cutoff_date = _now_utc() - timedelta(days=settings.delete_history_days)
                stmt = delete(Question).where(Question.created_at < cutoff_date)
                res = await db.execute(stmt)
                logger.info(f"[定时任务] 物理清理过期内容：抹除了 {res.rowcount} 条旧于 {settings.delete_history_days} 天的对话记录")

            # 容量阈值探针
            if settings.db_cleanup_size_gb > 0:
                try:
                    size_res = await db.execute(text("SELECT pg_database_size(current_database()) / 1024.0 / 1024.0 / 1024.0"))
                    db_size_gb = size_res.scalar()
                    if db_size_gb and db_size_gb > settings.db_cleanup_size_gb:
                        logger.warning(
                            f"[定时任务警报] 当前数据库物理空间占用 {db_size_gb:.2f}GB，已超过红线设定的 {settings.db_cleanup_size_gb}GB 容量！"
                        )
                except Exception as ex:
                    logger.debug(f"[定时任务] 容量探测失败 {ex}")

            # 清理过期导出任务（7天）
            try:
                count = report_export_service.cleanup_old_exports(days=7)
                db_count = await report_export_service.cleanup_old_export_jobs(db, days=7)
                if count > 0 or db_count > 0:
                    logger.info(f"[定时任务] 已清理过期导出任务：{count} 个文件，{db_count} 条数据库记录")
            except Exception as ex:
                logger.error(f"[定时任务] 清理导出相关记录失败: {ex}")

            await db.commit()
            if settings.batch_api_key:
                logger.info("[定时任务] 每日分析批量任务提交完成")
            else:
                logger.info(
                    f"[定时任务] 每日分析完成：处理 {result['processed_users']} 人，"
                    f"跳过 {result['skipped']} 人"
                )
        except Exception as e:
            await db.rollback()
            logger.error(f"[定时任务] 每日分析失败：{e}", exc_info=True)


async def _batch_poll_job() -> None:
    """
    轮询 batch 任务状态并在完成时回写日报。
    如果没有待处理的任务，则自动暂停轮询以节省资源并减少日志噪音。
    """
    if not settings.batch_api_key:
        return

    async with AsyncSessionLocal() as db:
        try:
            jobs = await analysis_service.list_pending_batch_jobs(db=db)
            if not jobs:
                # 数据库中已无可追踪任务，自动休眠当前 Job
                pause_batch_poll()
                return

            for job in jobs:
                await analysis_service.process_batch_job(db=db, job=job)

            await db.commit()
        except Exception as e:
            await db.rollback()
            logger.error(f"[定时任务] Batch 轮询失败：{e}", exc_info=True)


def pause_batch_poll() -> None:
    """
    暂停 Batch 轮询。
    """
    try:
        _scheduler.pause_job("batch_poll")
        logger.info("[定时任务] 检测到无活跃 Batch 任务，轮询已进入休眠模式。")
    except Exception:
        pass


def resume_batch_poll() -> None:
    """
    唤醒 Batch 轮询。
    """
    try:
        _scheduler.resume_job("batch_poll")
        logger.info("[定时任务] 已唤醒 Batch 结果轮询器。")
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
    """
    启动调度器。在 FastAPI lifespan 的 startup 事件中调用。
    注册每日凌晨 daily_analysis_hour 点执行的任务。
    """
    # 强制单例预检
    if _scheduler.running:
        logger.debug("[定时任务] 调度器已在运行中，跳过重复启动")
        return

    hour = settings.daily_analysis_hour
    # 每日分析任务 (Cron)
    _scheduler.add_job(
        _schedule_daily,
        trigger=CronTrigger(hour=hour, minute=0, timezone=timezone.utc),
        id="daily_analysis",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    # 批处理结果轮询 (Interval)
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
        logger.info(f"[定时任务] APScheduler 已启动，每日 {hour:02d}:00 执行分析")
        
        # 启动常驻导出异步工作线程
        _track_task(asyncio.create_task(_export_worker_loop()))
    except Exception as e:
        logger.error(f"[定时任务] 启动调度器失败: {e}")


async def stop_scheduler() -> None:
    """
    停止调度器。在 FastAPI lifespan 的 shutdown 事件中调用。
    使用超时机制防止任务挂死导致后端关不掉。
    """
    if _scheduler.running:
        try:
            _scheduler.shutdown(wait=False)
            logger.info("[定时任务] APScheduler 已停止")
        except Exception as e:
            logger.error(f"[定时任务] 停止调度器异常: {e}")

    if _tasks:
        living_tasks = [t for t in _tasks if not t.done()]
        if living_tasks:
            logger.info(f"[定时任务] 正在取消 {len(living_tasks)} 个运行中的异步子任务...")
            for task in living_tasks:
                task.cancel()
            
            try:
                # 给取消动作 5 秒的宽限期，避免 gather 无限期阻塞 shutdown 流程
                await asyncio.wait_for(
                    asyncio.gather(*living_tasks, return_exceptions=True),
                    timeout=5.0
                )
                logger.info("[定时任务] 所有子任务已清理完成")
            except asyncio.TimeoutError:
                logger.warning("[定时任务] 等待任务停止超时，强制跳过。")
            except Exception as e:
                logger.debug(f"[定时任务] 清理任务时发生非致命异常: {e}")
        
        _tasks.clear()
