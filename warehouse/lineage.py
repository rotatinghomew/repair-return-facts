"""更正血缘事实。

把“哪条更正改变了网点/对账岗看到的事实”显式连成链：

* 安装陈述被同工单更高修订取代 → 一条 installation 血缘；
* 被取代陈述关联的追偿被收回或冲正 → 关联到同一血缘，并挂接冲正单号；
* 权利行通过工单 + 修订号反查血缘（服务层负责）。
"""

from __future__ import annotations


def build_lineage(ownership: list[dict], reversals: list[dict]) -> list[dict]:
    by_work_order: dict[str, list[dict]] = {}
    for seg in ownership:
        by_work_order.setdefault(seg["work_order"], []).append(seg)

    reversal_by_wo: dict[str, list[dict]] = {}
    for rev in reversals:
        reversal_by_wo.setdefault(rev["work_order"], []).append(rev)

    lineage: list[dict] = []
    for work_order, segs in by_work_order.items():
        ordered = sorted(segs, key=lambda s: s["revision"])
        current = ordered[-1]
        for old in ordered[:-1]:
            entry = {
                "lineage_id": f"LIN-{work_order}-R{old['revision']}-R{current['revision']}",
                "subject": "installation",
                "part_key": old["part_key"],
                "work_order": work_order,
                "from_revision": old["revision"],
                "to_revision": current["revision"],
                "business_date_unchanged": old["valid_from"] == current["valid_from"],
                "backfilled_to": old["valid_from"],
                "correction_received": current["correction_received"],
                "changed_vehicle": old["vehicle"] != current["vehicle"],
                "old_vehicle": old["vehicle"],
                "new_vehicle": current["vehicle"],
                "reversal_ids": [r["reversal_id"] for r in reversal_by_wo.get(work_order, [])],
            }
            lineage.append(entry)
    return sorted(lineage, key=lambda e: (e["part_key"], e["work_order"], e["from_revision"]))
