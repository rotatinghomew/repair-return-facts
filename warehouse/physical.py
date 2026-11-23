"""实物在途与厂方签收事实。

归属（装在/装过哪台整机）与实物位置（在网点、在途、已到厂）是两条独立的事实链：

* 退回单的事件时间独立保留（``sent_at`` / ``received_at``）；
* 只有 ``received`` 才生成厂方签收事件，``in-transit`` 绝不因为入仓较晚、
  或出现新的拆装流水而被推断成“已装回/已签收”；
* 签收与工单证据是否吻合（同一配件、同一工单）在追偿结算环节判定。
"""

from __future__ import annotations

from datetime import date

from .loader import SourceBundle
from .timeutil import to_iso

INSTALLED = "installed"
IN_TRANSIT = "in-transit"
AT_FACTORY = "at-factory"

# 同日事件的先后等级：发运/登记在前，厂方签收在后（不能按事件名字母序）。
_EVENT_RANK = {"transit_registered": 1, "ship": 1, "factory_receipt": 2}


def build_physical(bundle: SourceBundle) -> dict:
    """返回每台配件的实物事件流与当前状态（按运行日由 pipeline 补充）。"""
    events_by_part: dict[str, list[dict]] = {}

    for ret in sorted(bundle.returns, key=lambda r: (r.part_key, r.sent_at or date.max)):
        chain = events_by_part.setdefault(ret.part_key, [])
        if ret.sent_at is not None:
            chain.append(
                {
                    "event": "ship",
                    "state": IN_TRANSIT,
                    "event_at": to_iso(ret.sent_at),
                    "return_id": ret.return_id,
                    "work_order": ret.work_order,
                }
            )
        if ret.state == "received":
            chain.append(
                {
                    "event": "factory_receipt",
                    "state": AT_FACTORY,
                    "event_at": to_iso(ret.received_at),
                    "return_id": ret.return_id,
                    "work_order": ret.work_order,
                }
            )
        elif ret.sent_at is None:
            # 没有发运日期的在途登记，只记录登记动作，绝不推断位置变化。
            chain.append(
                {
                    "event": "transit_registered",
                    "state": IN_TRANSIT,
                    "event_at": None,
                    "return_id": ret.return_id,
                    "work_order": ret.work_order,
                }
            )

    parts_view: dict[str, dict] = {}
    for key, chain in events_by_part.items():
        chain.sort(key=lambda e: (e["event_at"] or "", _EVENT_RANK.get(e["event"], 0), e["return_id"]))
        parts_view[key] = {"part_key": key, "events": chain, "current_state": chain[-1]["state"] if chain else INSTALLED}

    return {
        "parts": parts_view,
        # 退回单维度的扁平事实，便于对账岗按单号检索。
        "returns": [
            {
                "return_id": ret.return_id,
                "part_key": ret.part_key,
                "state": ret.state,
                "sent_at": to_iso(ret.sent_at),
                "received_at": to_iso(ret.received_at),
                "work_order": ret.work_order,
            }
            for ret in sorted(bundle.returns, key=lambda r: r.return_id)
        ],
    }
