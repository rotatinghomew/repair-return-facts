"""网点与对账岗的统一查询视图。

一次换装要能查到：归属（含未定窗口）、权利起止、在途或结算位置，
以及之后哪条更正改变了这些事实。所有方法都是只读、确定性的。
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from .timeutil import parse_date
from .rights import rights_on


class Serving:
    def __init__(self, warehouse: dict):
        self.w = warehouse

    # ---------- 配件视角 ----------
    def part_trace(self, part_key: str) -> dict:
        """一个配件的完整轨迹：归属段、实物事件、追偿、更正血缘。"""
        ownership = [s for s in self.w["fact_ownership"] if s["part_key"] == part_key]
        physical = self.w["fact_physical"]["parts"].get(
            part_key, {"part_key": part_key, "events": [], "current_state": "installed"}
        )
        claim_facts = [c for c in self.w["fact_claims"] if c["part_key"] == part_key]
        reversals = [r for r in self.w["fact_reversals"] if r["part_key"] == part_key]
        lineage = [e for e in self.w["fact_lineage"] if e["part_key"] == part_key]
        rights = [r for r in self.w["fact_rights"] if r["part_key"] == part_key]
        return {
            "part_key": part_key,
            "ownership": ownership,
            "current_physical_state": physical["current_state"],
            "physical_events": physical["events"],
            "rights": rights,
            "claims": claim_facts,
            "reversals": reversals,
            "lineage": lineage,
        }

    # ---------- 整机视角 ----------
    def vehicle_warranties(self, vehicle: str, on_day: Optional[date] = None) -> dict:
        """查当前（或指定日）权利；未定归属的权利单独列出，不影响其他明确对象。"""
        day = on_day or parse_date(self.w["run_date"])
        applicable = rights_on(self.w["fact_rights"], vehicle, day)
        determined = [r for r in applicable if r["status_as_of_run"] != "undetermined"]
        undetermined = [r for r in applicable if r["status_as_of_run"] == "undetermined"]
        return {
            "vehicle": vehicle,
            "as_of": day.isoformat(),
            "determined_rights": determined,
            "undetermined_rights": undetermined,
        }

    def vehicle_parts(self, vehicle: str) -> list[dict]:
        return [s for s in self.w["fact_ownership"] if s["vehicle"] == vehicle and s["status"] != "superseded"]

    # ---------- 追偿/对账视角 ----------
    def claim(self, claim_id: str) -> Optional[dict]:
        for claim in self.w["fact_claims"]:
            if claim["claim_id"] == claim_id:
                return claim
        return None

    def reversals_for_claim(self, claim_id: str) -> list[dict]:
        return [r for r in self.w["fact_reversals"] if r["claim_id"] == claim_id]

    def claims_awaiting_action(self) -> dict:
        """对账岗工作台：待核、待人工、可结算分组。"""
        buckets: dict[str, list[dict]] = {
            "pending_verification": [],
            "manual_review": [],
            "eligible_to_settle": [],
        }
        for claim in self.w["fact_claims"]:
            if claim["derived_state"] in buckets:
                buckets[claim["derived_state"]].append(claim)
        return buckets

    # ---------- 更正血缘 ----------
    def changes_affecting_work_order(self, work_order: str) -> list[dict]:
        return [e for e in self.w["fact_lineage"] if e["work_order"] == work_order]
