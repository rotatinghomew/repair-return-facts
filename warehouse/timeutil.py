"""日期与时间区间工具。

业务时间（维修日期、签收日期、销售日期）统一用 :class:`datetime.date` 表示；
区间一律采用左闭右开 ``[valid_from, valid_to)``，``valid_to is None`` 表示开放区间。
这样两段首尾相接的归属（一段止于 11-10、另一段起于 11-10）不会被误判为重叠。
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, timedelta
from typing import Optional

OPEN: Optional[date] = None


def parse_date(value: Optional[str]) -> Optional[date]:
    """解析 ISO ``YYYY-MM-DD`` 字符串；``None`` 透传。"""
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        raise ValueError(f"非法日期值: {value!r}")
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"非法日期值: {value!r}（应为 YYYY-MM-DD）") from exc


def to_iso(value: Optional[date]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def add_months(start: date, months: int) -> date:
    """返回 ``start`` 之后 ``months`` 个整月的对应日期（月末自动收敛）。"""
    total = start.month - 1 + months
    year = start.year + total // 12
    month = total % 12 + 1
    day = min(start.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def overlap(
    from_a: date,
    to_a: Optional[date],
    from_b: date,
    to_b: Optional[date],
) -> bool:
    """两个左闭右开区间是否相交。"""
    end_a = to_a or date.max
    end_b = to_b or date.max
    return from_a < end_b and from_b < end_a


def overlap_window(
    from_a: date,
    to_a: Optional[date],
    from_b: date,
    to_b: Optional[date],
) -> tuple[date, Optional[date]]:
    """返回相交子区间（调用方需先确认 :func:`overlap` 为真）。"""
    lo = max(from_a, from_b)
    hi = min(to_a or date.max, to_b or date.max)
    return lo, (None if hi == date.max else hi)


def contains(start: date, end: Optional[date], day: date) -> bool:
    """``day`` 是否落在左闭右开区间内。"""
    return start <= day and (end is None or day < end)


def inclusive_end(start: date, months: int) -> date:
    """保障期的末日（含）。边界日 = 起算日 + N 月，前一天为最后保障日。"""
    return add_months(start, months) - timedelta(days=1)
