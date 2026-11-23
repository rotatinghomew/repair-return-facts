"""源数据装载与结构校验。

只做结构性、标识范围层面的校验（外键缺失、同厂商配件号冲突等直接报错）；
业务冲突（同件归属相撞、两张工单争认同一旧件）不阻断入仓，而是保留事实、
在后续模块中标记为“待裁决/待人工确认”，网点仍可查询其他已明确的对象。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Optional

from .identifiers import part_key
from .timeutil import parse_date


@dataclass(frozen=True)
class Vehicle:
    serial: str
    sold_at: date


@dataclass(frozen=True)
class Part:
    key: str
    serial: str
    vendor: str
    warranty_months: int


@dataclass(frozen=True)
class Installation:
    """一次拆装陈述（可能是后续修订）。

    ``revision`` 为同一工单内的修订号，越大越新；
    ``correction_received`` 是更正到达事实仓的系统时间（迟到数据），
    业务有效期仍回补到 ``valid_from`` 对应的原维修日期。
    """

    part_key: str
    part_serial: str
    vendor: str
    vehicle: str
    valid_from: date
    valid_to: Optional[date]
    work_order: str
    revision: int
    recorded_at: date
    correction_received: Optional[date]


@dataclass(frozen=True)
class ReturnEvent:
    return_id: str
    part_key: str
    state: str  # in-transit | received
    sent_at: Optional[date]
    received_at: Optional[date]
    work_order: Optional[str]


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    part_key: str
    vehicle: str
    work_order: str
    state: str  # pending | accepted | settled
    receipt: Optional[str]
    reason: Optional[str]


@dataclass
class SourceBundle:
    vehicles: dict[str, Vehicle]
    parts: dict[str, Part]
    installations: list[Installation]
    returns: list[ReturnEvent]
    claims: list[ClaimRecord]
    rules: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _require(row: dict[str, Any], name: str, ctx: str) -> Any:
    if name not in row or row[name] in (None, ""):
        raise ValueError(f"{ctx} 缺少必填字段 {name!r}: {row}")
    return row[name]


def load_bundle(raw: dict[str, Any]) -> SourceBundle:
    warnings: list[str] = []

    vehicles: dict[str, Vehicle] = {}
    for row in raw.get("vehicles", []):
        serial = _require(row, "serial", "vehicles")
        if serial in vehicles:
            raise ValueError(f"整机编号重复，违反出厂唯一约束: {serial}")
        vehicles[serial] = Vehicle(serial=serial, sold_at=parse_date(_require(row, "sold_at", f"vehicle {serial}")))

    parts: dict[str, Part] = {}
    for row in raw.get("parts", []):
        serial = _require(row, "serial", "parts")
        vendor = _require(row, "vendor", f"part {serial}")
        key = part_key(vendor, serial)
        if key in parts:
            raise ValueError(f"配件号在同一厂商内不唯一: vendor={vendor}, serial={serial}")
        months = int(row.get("warranty_months", 0))
        if months <= 0:
            raise ValueError(f"配件 {key} 的 warranty_months 必须为正整数")
        parts[key] = Part(key=key, serial=serial, vendor=vendor, warranty_months=months)

    installations: list[Installation] = []
    for row in raw.get("installations", []):
        part_serial = _require(row, "part", "installations")
        vendor = _require(row, "vendor", "installations") if "vendor" in row else None
        if vendor is None:
            # 兼容只给配件号的夹具：由 parts 反查厂商。
            owners = [p for p in parts.values() if p.serial == part_serial]
            if len(owners) != 1:
                raise ValueError(
                    f"工单 {row.get('work_order')} 的配件 {part_serial} 无法唯一确定厂商，"
                    "请显式提供 vendor"
                )
            vendor = owners[0].vendor
        key = part_key(vendor, part_serial)
        if key not in parts:
            raise ValueError(f"工单 {row.get('work_order')} 引用了未登记配件 {key}")
        vehicle = _require(row, "vehicle", f"installation {row.get('work_order')}")
        if vehicle not in vehicles:
            raise ValueError(f"工单 {row.get('work_order')} 引用了未登记整机 {vehicle}")
        work_order = _require(row, "work_order", "installations")
        revision = int(row.get("revision", 1))
        correction = parse_date(row.get("correction_received"))
        recorded = correction or parse_date(row.get("recorded_at")) or parse_date(_require(row, "from", f"wo {work_order}"))
        installations.append(
            Installation(
                part_key=key,
                part_serial=part_serial,
                vendor=vendor,
                vehicle=vehicle,
                valid_from=parse_date(_require(row, "from", f"wo {work_order}")),
                valid_to=parse_date(row.get("to")),
                work_order=work_order,
                revision=revision,
                recorded_at=recorded,
                correction_received=correction,
            )
        )

    returns: list[ReturnEvent] = []
    for row in raw.get("returns", []):
        return_id = _require(row, "id", "returns")
        part_serial = _require(row, "part", f"return {return_id}")
        vendor = row.get("vendor")
        if vendor is None:
            owners = [p for p in parts.values() if p.serial == part_serial]
            if len(owners) != 1:
                raise ValueError(f"退回单 {return_id} 的配件 {part_serial} 无法唯一确定厂商")
            vendor = owners[0].vendor
        key = part_key(vendor, part_serial)
        if key not in parts:
            raise ValueError(f"退回单 {return_id} 引用了未登记配件 {key}")
        state = _require(row, "state", f"return {return_id}")
        if state not in {"in-transit", "received"}:
            raise ValueError(f"退回单 {return_id} 状态非法: {state}")
        if state == "received" and not row.get("received_at"):
            raise ValueError(f"退回单 {return_id} 已签收但缺少 received_at")
        returns.append(
            ReturnEvent(
                return_id=return_id,
                part_key=key,
                state=state,
                sent_at=parse_date(row.get("sent_at")),
                received_at=parse_date(row.get("received_at")),
                work_order=row.get("work_order"),
            )
        )

    claims: list[ClaimRecord] = []
    for row in raw.get("claims", []):
        claim_id = _require(row, "id", "claims")
        part_serial = _require(row, "part", f"claim {claim_id}")
        vendor = row.get("vendor")
        if vendor is None:
            owners = [p for p in parts.values() if p.serial == part_serial]
            if len(owners) != 1:
                raise ValueError(f"追偿 {claim_id} 的配件 {part_serial} 无法唯一确定厂商")
            vendor = owners[0].vendor
        key = part_key(vendor, part_serial)
        if key not in parts:
            raise ValueError(f"追偿 {claim_id} 引用了未登记配件 {key}")
        vehicle = _require(row, "vehicle", f"claim {claim_id}")
        if vehicle not in vehicles:
            raise ValueError(f"追偿 {claim_id} 引用了未登记整机 {vehicle}")
        state = _require(row, "state", f"claim {claim_id}")
        if state not in {"pending", "accepted", "settled"}:
            raise ValueError(f"追偿 {claim_id} 状态非法: {state}")
        claims.append(
            ClaimRecord(
                claim_id=claim_id,
                part_key=key,
                vehicle=vehicle,
                work_order=_require(row, "work_order", f"claim {claim_id}"),
                state=state,
                receipt=row.get("receipt"),
                reason=row.get("reason"),
            )
        )

    rules = raw.get("rules") or {}
    if not isinstance(rules, dict):
        raise ValueError("rules 必须为对象，例如 {\"vehicle_warranty_months\": 36}")

    return SourceBundle(
        vehicles=vehicles,
        parts=parts,
        installations=installations,
        returns=returns,
        claims=claims,
        rules=rules,
        warnings=warnings,
    )
