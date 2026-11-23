"""测试共用工具：从 data/ 装载源数据并构建事实仓。"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from warehouse import Serving, run

DATA_DIR = Path(__file__).parents[1] / "data"
RUN_DAY = date(2026, 11, 23)


def load_raw(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def build(name: str = "extended_facts.json", run_date: date = RUN_DAY) -> dict:
    return run(load_raw(name), run_date)


def serving(name: str = "extended_facts.json", run_date: date = RUN_DAY) -> Serving:
    return Serving(build(name, run_date))


def index(rows: list[dict], key: str) -> dict:
    return {row[key]: row for row in rows}
