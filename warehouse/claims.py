"""追偿生命周期与冲正事实。

追偿单的完整状态机（事实仓重算结果，不回写源系统）：

* ``pending_verification``：工单已完成，但换出旧件仍在途，先生成待核追偿；
* ``manual_review``：两张工单争认同一旧件（同一配件被不同工单追偿），留待人工确认；
* ``eligible_to_settle``：厂方已签收，且签收单与工单在“配件 + 工单”上证据吻合；
* ``settled``：源系统已确认结算/已接收且证据吻合；
* ``withdrawn``：更正换装对象后，尚未被厂方接收的追偿收回（原始行保留）；
* ``reversed``：凭证已被厂方接收/结算，不能删除，转为独立冲正事实（原始回执保留）。

设计约束：

* 较晚入仓的在途流水不会让任何待核追偿自动变成可结算——必须有签收事件且证据吻合；
* 冲正事实与原始追偿一对一保留，附更正来源工单/修订号与冲正生效时间；
* 被取代的安装陈述（superseded）是判断“追偿是否挂错件”的唯一依据。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

from .loader import ClaimRecord, SourceBundle
from .physical import AT_FACTORY, IN_TRANSIT
from .timeutil import overlap, parse_date, to_iso

PENDING_VERIFICATION = "pending_verification"
MANUAL_REVIEW = "manual_review"
ELIGIBLE_TO_SETTLE = "eligible_to_settle"
SETTLED = "settled"
WITHDRAWN = "withdrawn"
REVERSED = "reversed"

# 冲正事实类型
REV_WITHDRAWAL = "claim_withdrawal"
REV_REVERSAL = "claim_reversal"


@dataclass
class _Evidence:
    physical_state: str
    receipt_event_at: Optional[date]
    return_id: Optional[str]
    matches_work_order: bool


def _evidence_for(bundle: SourceBundle, physical: dict, claim: ClaimRecord) -> _Evidence:
    view = physical["parts"].get(claim.part_key)
    state = view["current_state"] if view else "installed"
    receipt_at: Optional[date] = None
    return_id: Optional[str] = None
    matches = False
    # 只接受与本工单挂钩的签收单作为证据；其他工单对同一配件的签收不能充数。
    for ret in physical["returns"]:
        if ret["part_key"] != claim.part_key or ret["work_order"] != claim.work_order:
            continue
        if ret["state"] == "received":
            receipt_at = parse_date(ret["received_at"])
            return_id = ret["return_id"]
            matches = True
    return _Evidence(state, receipt_at, return_id, matches)


def _revision_maps(ownership: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """按工单号返回（被取代陈述, 当前陈述）映射。"""
    by_work_order: dict[str, list[dict]] = {}
    for seg in ownership:
        by_work_order.setdefault(seg["work_order"], []).append(seg)
    superseded: dict[str, dict] = {}
    current: dict[str, dict] = {}
    for work_order, segs in by_work_order.items():
        ordered = sorted(segs, key=lambda s: s["revision"])
        top = ordered[-1]
        current[work_order] = top
        if top["status"] == "superseded":
            continue
        for old in ordered[:-1]:
            superseded[work_order] = old
    return superseded, current


def _contention(claims: list[ClaimRecord], ownership: list[dict]) -> set[str]:
    """两张工单争认同一换出旧件 → 全部转人工确认。

    同一配件在不同工单上的“先后换装”（归属窗口首尾相接、互不重叠）是正常流转，
    只有两张工单的归属窗口在业务时间上重叠、旧件归属本身未裁定时，才算争认。
    """
    segments = [
        s
        for s in ownership
        if s["status"] != "superseded"
    ]
    by_part: dict[str, list[dict]] = {}
    for seg in segments:
        by_part.setdefault(seg["part_key"], []).append(seg)

    contentious_work_orders: set[str] = set()
    for key, segs in by_part.items():
        for i, a in enumerate(segs):
            for b in segs[i + 1 :]:
                if a["work_order"] == b["work_order"] or a["vehicle"] == b["vehicle"]:
                    continue
                if overlap(
                    parse_date(a["valid_from"]),
                    parse_date(a["valid_to"]) if a["valid_to"] else None,
                    parse_date(b["valid_from"]),
                    parse_date(b["valid_to"]) if b["valid_to"] else None,
                ):
                    contentious_work_orders.update({a["work_order"], b["work_order"]})

    return {claim.claim_id for claim in claims if claim.work_order in contentious_work_orders}


def build_claims(
    bundle: SourceBundle,
    ownership: list[dict],
    physical: dict,
    run_date: date,
) -> tuple[list[dict], list[dict]]:
    superseded, current = _revision_maps(ownership)
    contended = _contention(bundle.claims, ownership)
    part_vendor = {key: part.vendor for key, part in bundle.parts.items()}

    facts: list[dict] = []
    reversals: list[dict] = []

    for claim in sorted(bundle.claims, key=lambda c: c.claim_id):
        evidence = _evidence_for(bundle, physical, claim)
        wrong_installation = superseded.get(claim.work_order)
        vendor = part_vendor[claim.part_key]

        derived_state, hold_reason = _derive_state(claim, evidence, wrong_installation, claim.claim_id in contended)

        fact = {
            "claim_id": claim.claim_id,
            "part_key": claim.part_key,
            "vendor": vendor,
            "vehicle": claim.vehicle,
            "work_order": claim.work_order,
            "reason": claim.reason,
            "source_state": claim.state,
            "source_receipt": claim.receipt,
            "derived_state": derived_state,
            "hold_reason": hold_reason,
            "physical_state_at_run": evidence.physical_state,
            "factory_receipt_at": to_iso(evidence.receipt_event_at),
            "return_id": evidence.return_id,
            "evidence_matches_work_order": evidence.matches_work_order,
            "as_of_run": to_iso(run_date),
            "superseded_by": (
                {
                    "work_order": claim.work_order,
                    "revision": current[claim.work_order]["revision"],
                    "correction_received": current[claim.work_order]["correction_received"],
                }
                if claim.work_order in superseded
                else None
            ),
        }
        facts.append(fact)

        # 更正换装对象后的两条处理路径（冲正事实独立留存，原始回执不删）。
        if claim.work_order in superseded:
            correction = current[claim.work_order]
            wrong_installation = superseded[claim.work_order]
            # 冲正/收回到更正到达日生效；更正到达日缺失时才回退到运行日。
            effective_at = parse_date(correction["correction_received"]) if correction["correction_received"] else run_date
            if claim.state in {"accepted", "settled"}:
                fact["derived_state"] = REVERSED
                fact["hold_reason"] = "换装对象更正：已接收凭证转独立冲正，待对账岗处理"
                reversals.append(
                    {
                        "reversal_id": f"REV-{claim.claim_id}",
                        "reversal_type": REV_REVERSAL,
                        "claim_id": claim.claim_id,
                        "part_key": claim.part_key,
                        "vendor": vendor,
                        "work_order": claim.work_order,
                        "original_receipt": claim.receipt,
                        "original_state": claim.state,
                        "effective_at": to_iso(effective_at),
                        "reason": "换装对象更正：厂方已接收凭证需冲正，原始凭证与回执保留",
                        "correction": fact["superseded_by"],
                    }
                )
            elif claim.claim_id not in contended:
                fact["derived_state"] = WITHDRAWN
                fact["hold_reason"] = "换装对象更正：未结算追偿已收回"
                reversals.append(
                    {
                        "reversal_id": f"REV-{claim.claim_id}",
                        "reversal_type": REV_WITHDRAWAL,
                        "claim_id": claim.claim_id,
                        "part_key": claim.part_key,
                        "vendor": vendor,
                        "work_order": claim.work_order,
                        "original_receipt": claim.receipt,
                        "original_state": claim.state,
                        "effective_at": to_iso(effective_at),
                        "reason": "换装对象更正：未结算追偿收回",
                        "correction": fact["superseded_by"],
                    }
                )

    return facts, reversals


def _derive_state(
    claim: ClaimRecord,
    evidence: _Evidence,
    wrong_installation: Optional[dict],
    is_contended: bool,
) -> tuple[str, Optional[str]]:
    # 争认同一旧件优先转人工，避免在途/签收判断掩盖责任冲突。
    if is_contended:
        return MANUAL_REVIEW, "两张工单争认同一换出旧件，待人工确认"

    if evidence.physical_state == IN_TRANSIT:
        return PENDING_VERIFICATION, "旧件在途，待厂方签收并与工单证据核对"

    if evidence.physical_state == AT_FACTORY:
        if not evidence.matches_work_order:
            return MANUAL_REVIEW, "签收实物与工单证据不吻合，待人工核对"
        if claim.state in {"accepted", "settled"}:
            return SETTLED, None
        return ELIGIBLE_TO_SETTLE, "已签收且证据吻合，可交厂结算"

    # 未登记退回流水：源系统状态维持待核，不做任何实物位置推断。
    if claim.state == "pending":
        return PENDING_VERIFICATION, "未见退回/签收流水，保持待核"
    return claim.state, None
