"""配件归属事实（含双时间与相撞裁决）。

规则要点：

1. 同一工单的多次陈述按 ``revision`` 取最新，旧陈述置为 ``superseded``，
   更正的业务有效期回补到原维修日期（``valid_from`` 不变），
   系统时间保留在 ``recorded_at / correction_received``，形成双时间。
2. 一个配件在同一业务时间只能归属一台整机。不同整机的有效期相撞且尚无裁决时，
   相撞窗口标记为 ``disputed``，并给出“未定归属”的窗口；网点仍可查询该整机
   其他已明确（``effective``）的质保对象。
3. 同一整机上首尾相接的换装链（一段的 ``valid_to`` 等于另一段的 ``valid_from``）
   属于正常换装，不算冲突——区间统一左闭右开。
4. 迟到入仓的在途流水不会改写归属：归属只来自拆装陈述，实物位置由
   :mod:`warehouse.physical` 独立维护。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from .loader import Installation, SourceBundle
from .timeutil import overlap, overlap_window, to_iso

EFFECTIVE = "effective"
DISPUTED = "disputed"
SUPERSEDED = "superseded"


@dataclass
class OwnershipSegment:
    part_key: str
    part_serial: str
    vendor: str
    vehicle: str
    work_order: str
    revision: int
    valid_from: date
    valid_to: Optional[date]
    status: str
    recorded_at: date
    correction_received: Optional[date]
    conflict_with: list[dict] = field(default_factory=list)
    undetermined_windows: list[dict] = field(default_factory=list)


def _pick_current_installations(bundle: SourceBundle) -> tuple[list[Installation], list[Installation]]:
    """按工单号分组取最高修订；被取代的旧陈述单独返回。"""
    by_work_order: dict[str, list[Installation]] = {}
    for inst in bundle.installations:
        by_work_order.setdefault(inst.work_order, []).append(inst)

    current: list[Installation] = []
    superseded: list[Installation] = []
    for rows in by_work_order.values():
        rows_sorted = sorted(rows, key=lambda r: r.revision)
        current.append(rows_sorted[-1])
        superseded.extend(rows_sorted[:-1])
    return current, superseded


def build_ownership(bundle: SourceBundle) -> list[dict]:
    current, superseded = _pick_current_installations(bundle)
    segments: list[OwnershipSegment] = []

    for inst in sorted(current, key=lambda r: (r.part_key, r.valid_from, r.work_order)):
        segments.append(
            OwnershipSegment(
                part_key=inst.part_key,
                part_serial=inst.part_serial,
                vendor=inst.vendor,
                vehicle=inst.vehicle,
                work_order=inst.work_order,
                revision=inst.revision,
                valid_from=inst.valid_from,
                valid_to=inst.valid_to,
                status=EFFECTIVE,
                recorded_at=inst.recorded_at,
                correction_received=inst.correction_received,
            )
        )

    # 两两检测同一配件在不同整机上的时间相撞（同整机的换装链不算冲突）。
    for i, seg_a in enumerate(segments):
        for seg_b in segments[i + 1 :]:
            if seg_a.part_key != seg_b.part_key:
                continue
            if seg_a.vehicle == seg_b.vehicle:
                continue
            if not overlap(seg_a.valid_from, seg_a.valid_to, seg_b.valid_from, seg_b.valid_to):
                continue
            win_lo, win_hi = overlap_window(
                seg_a.valid_from, seg_a.valid_to, seg_b.valid_from, seg_b.valid_to
            )
            window = {"from": to_iso(win_lo), "to": to_iso(win_hi)}
            for seg, other in ((seg_a, seg_b), (seg_b, seg_a)):
                seg.status = DISPUTED
                seg.conflict_with.append(
                    {"work_order": other.work_order, "vehicle": other.vehicle, "revision": other.revision}
                )
                if window not in seg.undetermined_windows:
                    seg.undetermined_windows.append(window)

    # 被修订取代的历史陈述原样保留（只作血缘，不再参与权利计算）。
    for inst in superseded:
        segments.append(
            OwnershipSegment(
                part_key=inst.part_key,
                part_serial=inst.part_serial,
                vendor=inst.vendor,
                vehicle=inst.vehicle,
                work_order=inst.work_order,
                revision=inst.revision,
                valid_from=inst.valid_from,
                valid_to=inst.valid_to,
                status=SUPERSEDED,
                recorded_at=inst.recorded_at,
                correction_received=inst.correction_received,
            )
        )

    return [_serialize(seg) for seg in sorted(segments, key=_sort_key)]


def _sort_key(seg: OwnershipSegment) -> tuple:
    return (seg.part_key, seg.valid_from, seg.work_order, seg.revision)


def _serialize(seg: OwnershipSegment) -> dict:
    return {
        "part_key": seg.part_key,
        "part_serial": seg.part_serial,
        "vendor": seg.vendor,
        "vehicle": seg.vehicle,
        "work_order": seg.work_order,
        "revision": seg.revision,
        "valid_from": to_iso(seg.valid_from),
        "valid_to": to_iso(seg.valid_to),
        "status": seg.status,
        "recorded_at": to_iso(seg.recorded_at),
        "correction_received": to_iso(seg.correction_received),
        "conflict_with": seg.conflict_with,
        "undetermined_windows": seg.undetermined_windows,
    }
