"""时区口径：日期一律按 UTC 存储，按研究中心所在时区展示与判定“今天/是否同一天”。

临床访视在业务上是**当地日历日**（窗口按日历日前后 N 天），因此：

- 事件发生的时刻（改期、提交、锁库、修订生效）以 UTC 时间戳持久化
  （``DateTime(timezone=True)``）；
- 访视计划/实际日期持久化为 ``date``，语义固定为「研究中心当地日历日」，
  不随时区换算漂移，窗口算术也始终在当地日历日上进行（天然不受夏令时影响）；
- 需要判断“现在是当地哪一天 / 两个 UTC 时刻在当地是否同一天”时，
  统一走本模块，禁止用 ``date.today()`` 代替（服务器在 UTC，下午的北京
  已经是第二天）。
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULT_TIMEZONE = "Asia/Shanghai"
_UTC = timezone.utc


def get_zone(tz_name: str | None) -> ZoneInfo:
    """取 IANA 时区；配置缺失/非法时回退 UTC（不允许把异常抛给业务流程）。"""
    if not tz_name:
        return ZoneInfo(DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo(DEFAULT_TIMEZONE)


def now_utc() -> datetime:
    return datetime.now(_UTC)


def to_local(value: datetime, tz_name: str | None) -> datetime:
    """把感知/朴素时间戳转到研究中心当地时区（朴素值视为 UTC）。"""
    if value.tzinfo is None:
        value = value.replace(tzinfo=_UTC)
    return value.astimezone(get_zone(tz_name))


def local_date(value: datetime, tz_name: str | None) -> date:
    return to_local(value, tz_name).date()


def local_today(tz_name: str | None, *, now: datetime | None = None) -> date:
    """研究中心当地的今天。甘特“今日列”、窗期红点均以此为准。"""
    return local_date(now or now_utc(), tz_name)


def same_local_day(a: datetime, b: datetime, tz_name: str | None) -> bool:
    """两个 UTC 时刻在研究中心当地是否同一日历日（跨时区 / 夏令时判定入口）。"""
    return local_date(a, tz_name) == local_date(b, tz_name)


def add_days(d: date, days: int) -> date:
    """当地日历日加减。日历日算术与 DST 无关，不会出现 23/25 小时偏移。"""
    return d + timedelta(days=days)


def date_display_anchor(d: date, tz_name: str | None) -> str:
    """当地正午作为该日历日的唯一 UTC 锚点 ISO 串。

    取正午是为了让该时间点在任意 UTC 偏移（-12~+14）下都落在同一个当地日历日，
    供不具备时区库的外部消费方（Excel 等）排序/展示时不跨日。
    """
    return datetime.combine(d, time(12, 0), tzinfo=get_zone(tz_name)).isoformat()


def format_local(value: datetime, tz_name: str | None, *, with_time: bool = True) -> str:
    """留痕时间戳的统一展示格式：当地时区 YYYY-MM-DD HH:MM（UTC 偏移附注）。"""
    dt = to_local(value, tz_name)
    base = dt.strftime("%Y-%m-%d %H:%M") if with_time else dt.strftime("%Y-%m-%d")
    offset = dt.strftime("%z")
    offset_txt = f"UTC{offset[:3]}:{offset[3:]}" if offset else "UTC"
    return f"{base}（{offset_txt}）"
