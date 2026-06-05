from datetime import date, datetime, time, timedelta

from app.core.config import CHINA_TZ


def now_biz() -> datetime:
    return datetime.now(CHINA_TZ)


def today_biz() -> date:
    return now_biz().date()


def yesterday_biz() -> date:
    return today_biz() - timedelta(days=1)


def yesterday_biz_iso_date() -> str:
    return yesterday_biz().isoformat()


def now_biz_dt_for_db() -> datetime:
    return now_biz()


def ensure_biz_dt(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=CHINA_TZ)
    return value.astimezone(CHINA_TZ)


def biz_day_range(date_str: str) -> tuple[datetime, datetime]:
    day = date.fromisoformat(date_str)
    start = datetime.combine(day, time.min, tzinfo=CHINA_TZ)
    return start, start + timedelta(days=1)


def days_ago_biz(days: int) -> datetime:
    return now_biz() - timedelta(days=days)
