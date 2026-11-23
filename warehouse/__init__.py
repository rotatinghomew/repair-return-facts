"""备件换装质保事实仓。

对外只暴露两个入口：

* :func:`run` —— 按给定运行日把源数据全量重算为事实仓（幂等，可每天重跑）；
* :class:`Serving` —— 网点与对账岗使用的查询视图（归属、权利、在途/结算、更正血缘）。
"""

from .serving import Serving

__all__ = ["run", "Serving"]


def run(raw, run_date=None):
    """延迟导入，避免 ``python -m warehouse.pipeline`` 时的模块重复加载告警。"""
    from .pipeline import run as _run

    return _run(raw, run_date)
