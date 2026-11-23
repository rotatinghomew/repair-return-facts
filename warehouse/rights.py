"""质保权利事实。

两类权利按公开规则共同适用、互不替代：

* ``vehicle_base``：原机保护期，自销售日起算整月；
* ``replacement_part``：换件保障，跟随实际装入的件，自该件装入整机的
  维修日期起算，期限取配件厂商公开的 ``warranty_months``。

每条权利都保留来源（销售记录 / 工单号 + 修订号）、适用起止日（含末日）、
双时间与当前状态。被修订取代的归属不产生当前权利；归属未定（disputed）的窗口，
对应权利也标记为 ``undetermined``，但整机其他已明确对象的权利照常可查。
"""

from __future__ import annotations

from datetime import date

from .loader import SourceBundle
from .timeutil import inclusive_end, parse_date, to_iso

VEHICLE_BASE = "vehicle_base"
REPLACEMENT_PART = "replacement_part"

ACTIVE = "active"
EXPIRED = "expired"
UNDETERMINED = "undetermined"


def build_rights(bundle: SourceBundle, ownership: list[dict], run_date: date) -> list[dict]:
    rights: list[dict] = []
    base_months = bundle_rules(bundle).get("vehicle_warranty_months", 36)

    # 1) 原机保护期（来源：销售记录）。
    for vehicle in sorted(bundle.vehicles.values(), key=lambda v: v.serial):
        end = inclusive_end(vehicle.sold_at, base_months)
        rights.append(
            {
                "right_id": f"RIGHT-V-{vehicle.serial}",
                "right_type": VEHICLE_BASE,
                "vehicle": vehicle.serial,
                "part_key": None,
                "source": {"kind": "sale", "sold_at": to_iso(vehicle.sold_at)},
                "applies_from": to_iso(vehicle.sold_at),
                "applies_to": to_iso(end),
                "boundary_rule": f"销售日 + {base_months} 个月，末日含",
                "recorded_at": to_iso(vehicle.sold_at),
                "correction_received": None,
                "work_order": None,
                "revision": None,
                "status_as_of_run": _status(vehicle.sold_at, end, run_date, False),
            }
        )

    # 2) 换件保障：仅对当前有效（effective / disputed）的归属段生成。
    for seg in ownership:
        if seg["status"] == "superseded":
            continue
        part = bundle.parts[seg["part_key"]]
        start = parse_date(seg["valid_from"])
        end = inclusive_end(start, part.warranty_months)
        rights.append(
            {
                "right_id": f"RIGHT-P-{seg['work_order']}-R{seg['revision']}",
                "right_type": REPLACEMENT_PART,
                "vehicle": seg["vehicle"],
                "part_key": seg["part_key"],
                "source": {
                    "kind": "installation",
                    "work_order": seg["work_order"],
                    "revision": seg["revision"],
                    "vendor": seg["vendor"],
                },
                "applies_from": to_iso(start),
                "applies_to": to_iso(end),
                "boundary_rule": f"装入日 + {part.warranty_months} 个月（厂商 {seg['vendor']} 公开规则），末日含",
                "recorded_at": seg["recorded_at"],
                "correction_received": seg["correction_received"],
                "work_order": seg["work_order"],
                "revision": seg["revision"],
                "status_as_of_run": _status(start, end, run_date, seg["status"] == "disputed"),
                "undetermined_windows": list(seg["undetermined_windows"]),
            }
        )

    return rights


def _status(start: date, end: date, run_date: date, disputed: bool) -> str:
    if disputed:
        return UNDETERMINED
    if start <= run_date <= end:
        return ACTIVE
    if run_date < start:
        return ACTIVE  # 已登记但尚未起算，网点视角仍属有效权利
    return EXPIRED


def bundle_rules(bundle: SourceBundle) -> dict:
    """源数据可携带公开规则；缺省原机保护期 36 个月。"""
    rules = getattr(bundle, "rules", None) or {}
    return {"vehicle_warranty_months": rules.get("vehicle_warranty_months", 36)}


def rights_on(rights: list[dict], vehicle: str, on_day: date) -> list[dict]:
    """查询某整机在指定日期适用的权利（含来源与适用日期）。"""
    day = on_day
    out: list[dict] = []
    for right in rights:
        if right["vehicle"] != vehicle:
            continue
        lo = parse_date(right["applies_from"])
        hi = parse_date(right["applies_to"])
        if lo <= day <= hi:
            out.append(right)
    return out
