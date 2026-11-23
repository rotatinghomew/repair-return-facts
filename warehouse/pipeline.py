"""每日可重跑的事实仓流水线。

幂等保证：

* 全量重算，不做增量 upsert/删除——同一 ``run_date`` 对同一输入必然产出同一事实仓；
* 所有事实行带 ``as_of_run``（运行日）与业务事件时间，迟到数据通过双时间表达，
  绝不回改已被厂方接收的原始凭证（只追加冲正事实）；
* 输出为纯 JSON 兼容结构，可整体覆盖落地。
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any, Optional

from .claims import build_claims
from .lineage import build_lineage
from .loader import load_bundle
from .ownership import build_ownership
from .physical import build_physical
from .rights import build_rights, bundle_rules
from .timeutil import parse_date, to_iso

FACT_VERSION = 1


def run(raw: dict[str, Any], run_date: Optional[date] = None) -> dict[str, Any]:
    """把源数据重算为事实仓。纯函数，便于测试与每日重跑。"""
    run_day = run_date or parse_date(raw.get("run_date")) or date.today()
    bundle = load_bundle(raw)

    ownership = build_ownership(bundle)
    physical = build_physical(bundle)
    rights = build_rights(bundle, ownership, run_day)
    claim_facts, reversals = build_claims(bundle, ownership, physical, run_day)
    lineage = build_lineage(ownership, reversals)

    return {
        "fact_version": FACT_VERSION,
        "run_date": to_iso(run_day),
        "dim_vehicles": [
            {"serial": v.serial, "sold_at": to_iso(v.sold_at)}
            for v in sorted(bundle.vehicles.values(), key=lambda v: v.serial)
        ],
        "dim_parts": [
            {
                "part_key": p.key,
                "part_serial": p.serial,
                "vendor": p.vendor,
                "warranty_months": p.warranty_months,
            }
            for p in sorted(bundle.parts.values(), key=lambda p: p.key)
        ],
        "fact_ownership": ownership,
        "fact_physical": physical,
        "fact_rights": rights,
        "fact_claims": claim_facts,
        "fact_reversals": reversals,
        "fact_lineage": lineage,
        "applied_rules": {
            "vehicle_warranty_months": bundle_rules(bundle)["vehicle_warranty_months"],
            "part_warranty_months_source": "dim_parts.warranty_months（厂商公开规则）",
        },
        "source_warnings": bundle.warnings,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="备件换装质保事实仓每日重跑")
    parser.add_argument("--input", required=True, help="源数据 JSON 路径")
    parser.add_argument("--output", required=True, help="事实仓输出 JSON 路径（整体覆盖）")
    parser.add_argument("--run-date", dest="run_date", default=None, help="运行日 YYYY-MM-DD，缺省取源数据或当天")
    args = parser.parse_args(argv)

    raw = json.loads(Path(args.input).read_text(encoding="utf-8"))
    run_day = parse_date(args.run_date) if args.run_date else None
    warehouse = run(raw, run_day)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(warehouse, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")
    print(
        f"事实仓已写出: {out} "
        f"(归属段 {len(warehouse['fact_ownership'])}, 权利 {len(warehouse['fact_rights'])}, "
        f"追偿 {len(warehouse['fact_claims'])}, 冲正 {len(warehouse['fact_reversals'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
