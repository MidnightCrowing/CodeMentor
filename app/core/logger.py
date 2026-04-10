import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

from app.core.config import CHINA_TZ, settings


class DailyFolderFileHandler(logging.Handler):
    def __init__(
        self,
        base_dir: Path,
        filename: str,
        level: int = logging.NOTSET,
        encoding: str = "utf-8",
    ):
        super().__init__(level)
        self.base_dir = Path(base_dir)
        self.filename = filename
        self.encoding = encoding
        self._current_date = self._today()
        self._stream = None
        self._open_stream()

    def _today(self) -> str:
        return datetime.now(CHINA_TZ).date().isoformat()

    def _log_path(self) -> Path:
        day_dir = self.base_dir / self._current_date
        day_dir.mkdir(parents=True, exist_ok=True)
        return day_dir / self.filename

    def _open_stream(self) -> None:
        path = self._log_path()
        self._stream = open(path, "a", encoding=self.encoding)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.acquire()
            current = self._today()
            if current != self._current_date:
                self._current_date = current
                if self._stream:
                    self._stream.close()
                self._open_stream()
            msg = self.format(record)
            if self._stream:
                self._stream.write(msg + "\n")
                self._stream.flush()
        except Exception:
            self.handleError(record)
        finally:
            self.release()

    def close(self) -> None:
        try:
            if self._stream:
                self._stream.close()
                self._stream = None
        finally:
            super().close()


def setup_logging():
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s:%(lineno)d - %(message)s")

    class _IgnoreCancelledPoolClose(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.name.startswith("sqlalchemy.pool"):
                if record.exc_info and isinstance(record.exc_info[1], asyncio.CancelledError):
                    return False
                msg = record.getMessage()
                if "CancelledError" in msg and "terminate" in msg:
                    return False
            return True

    class _IgnoreApschedulerInfo(logging.Filter):
        def filter(self, record: logging.LogRecord) -> bool:
            if record.name.startswith("apscheduler") and record.levelno < logging.WARNING:
                return False
            return True

    ignore_cancelled_pool = _IgnoreCancelledPoolClose()
    ignore_apscheduler_info = _IgnoreApschedulerInfo()

    error_handler = DailyFolderFileHandler(log_dir, "error.log", level=logging.ERROR)
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(fmt)
    error_handler.addFilter(ignore_cancelled_pool)
    error_handler.addFilter(ignore_apscheduler_info)

    app_handler = DailyFolderFileHandler(log_dir, "app.log", level=logging.INFO)
    app_handler.setLevel(logging.INFO)
    app_handler.setFormatter(fmt)
    app_handler.addFilter(ignore_cancelled_pool)
    app_handler.addFilter(ignore_apscheduler_info)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(fmt)
    console_handler.addFilter(ignore_cancelled_pool)
    console_handler.addFilter(ignore_apscheduler_info)

    ai_handler = DailyFolderFileHandler(log_dir, "ai.log", level=logging.INFO)
    ai_handler.setLevel(logging.INFO)
    ai_handler.setFormatter(fmt)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    root_logger.addHandler(error_handler)
    root_logger.addHandler(app_handler)
    root_logger.addHandler(console_handler)

    ai_logger = logging.getLogger("ai")
    if ai_logger.hasHandlers():
        ai_logger.handlers.clear()
    ai_logger.addHandler(ai_handler)
    ai_logger.propagate = False

    access_handler = DailyFolderFileHandler(log_dir, "access.log", level=logging.INFO)
    access_handler.setLevel(logging.INFO)
    access_handler.setFormatter(logging.Formatter("%(asctime)s - %(message)s"))

    uvicorn_access_logger = logging.getLogger("uvicorn.access")
    if uvicorn_access_logger.hasHandlers():
        uvicorn_access_logger.handlers.clear()
    uvicorn_access_logger.addHandler(access_handler)
    uvicorn_access_logger.propagate = False

    sqlalchemy_logger = logging.getLogger("sqlalchemy.engine")
    sqlalchemy_logger.setLevel(logging.WARNING)
    sqlalchemy_logger.addHandler(error_handler)
    sqlalchemy_logger.addHandler(app_handler)

    # APScheduler 仅保留 WARNING 及以上，避免大量心跳日志淹没业务日志。
    logging.getLogger("apscheduler").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.executors.default").setLevel(logging.WARNING)
    logging.getLogger("apscheduler.scheduler").setLevel(logging.WARNING)

    logging.getLogger(__name__).info("日志系统已启动，按日期分目录写入日志文件")
