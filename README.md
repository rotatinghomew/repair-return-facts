# 备件换装质保事实仓

归并整机与配件的生产归属、网点换装、在途退回、厂方签收和上游追偿凭据，输出一组
**每天可全量重跑**的事实表，防止同一张凭证既被拿去追偿又被当成有效质保重复使用。

## 能力

- **标识范围隔离**：整机编号出厂全局唯一；配件号仅在所属厂商内唯一，仓内以 `厂商/配件号` 限定。
- **双时间归属**：拆装更正回补到原维修日期，更正到达时间独立保留；同件同时只能归属一台整机，
  相撞未裁决时标出未定窗口，整机其他明确质保对象仍可查。
- **实物与归属解耦**：在途/签收是独立事件流，迟到的在途流水不会把配件推断成已装回或已签收。
- **质保重算**：原机保护期（销售日起算）与换件保障（跟随实际装入件、按厂商公开月数）共同适用，
  每条权利带来源、适用起止日与状态；更正后当前质保不再挂错件。
- **追偿状态机**：工单完成但旧件在途可生成待核追偿；签收与工单证据吻合才可结算；
  两单争认同一旧件转人工；未结算追偿收回，已被厂方接收的凭证追加独立冲正事实并保留原始回执。
- **更正血缘**：从一次换装可追到归属、权利起止、在途/结算位置，以及之后哪条更正改变了这些事实。

模型细节与规则见 [`docs/fact_model.md`](docs/fact_model.md)。

## 目录

```
warehouse/   事实仓实现（装载、归属、实物、权利、追偿/冲正、血缘、服务视图、流水线）
data/        源数据夹具：facts.json（原始）、extended_facts.json（覆盖全部规则的场景）
tests/       规则测试，不依赖网络或第三方包
docs/        模型与规则说明
```

需要 Python 3.11 或更新版本。

## 每日重跑

```bash
python3 -m warehouse.pipeline \
  --input data/extended_facts.json \
  --output out/warehouse.json \
  --run-date 2026-11-23
```

流水线是纯函数式全量重建：同输入、同运行日输出完全一致，输出文件整体覆盖，可安全重复调度。

## 查询示例

```python
from datetime import date
from warehouse import Serving, run

warehouse = run(raw, date(2026, 11, 23))
view = Serving(warehouse)

view.vehicle_warranties("CAR-1")                       # 当前权利（明确/未定分开）
view.part_trace("V-A/P-601")                           # 一次换装的完整轨迹
view.claims_awaiting_action()                          # 待核/待人工/可结算工作桶
view.changes_affecting_work_order("WO-601")            # 哪条更正改变了事实
```

## 测试

```bash
python3 -m unittest discover -s tests
```
