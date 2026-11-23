"""标识分配范围。

* 整机编号（vehicle serial）出厂后保持，全局唯一；
* 配件号只在所属厂商内唯一，因此配件身份必须用 ``厂商/配件号`` 限定，
  不同厂商下相同配件序列号不得被当成同一个实物。
"""

from __future__ import annotations


def part_key(vendor: str, serial: str) -> str:
    """配件的全局限定标识。"""
    if not vendor or not serial:
        raise ValueError(f"配件标识缺少厂商或序列号: vendor={vendor!r}, serial={serial!r}")
    return f"{vendor}/{serial}"


def split_part_key(key: str) -> tuple[str, str]:
    vendor, serial = key.split("/", 1)
    return vendor, serial
