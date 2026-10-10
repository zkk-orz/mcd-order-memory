# 写操作 schema 级实现（六工具，均不实测——用户裁决，按官方 schema 构造）

**共同铁律（四道闸）**：①预览（calculate-price 实算后的完整清单+实付价）→ ②明确确认词（用户说"确认/下单"才执行；"行吧/看着办"必须追问）→ ③执行：调用时在 mcp_client.py 命令末尾**追加 `--i-confirm`**（脚本层强制，缺它直接拒绝）→ ④回报：成功给订单号，失败给**报错原文**+保留清单供用户去官方渠道完成。

首次启用：检测到 MCD_MCP_TOKEN 后先问一次"是否启用真实下单？"记住答案（对用户只问这一次）。

## create-order（真实下单，扣钱）

| 参数 | 说明 |
|---|---|
| storeCode+orderType+beType | 必填；到店=orderType 1+beType 1；得来速=1+5+beCode；外送=2+2+addressId+beCode；团餐=2+6+addressId+beCode+gmServiceCode |
| items[] | **productCode**+quantity（同 calculate-price；可带 couponId/modification） |
| takeWayCode | **到店/得来速必传**——取 calculate-price 返回的 takeWayList 中用户选的 code（eat-in 堂食/take-in-store 外带） |
| addressId | 外送/团餐必填（delivery-query-addresses） |
| needTableware / remark | 餐具（默认问一句或 true）；备注≤50 字仅外送 |

前置链：query-nearby-stores（或 delivery-query-stores）→ query-meals → calculate-price（**必须先算价拿 takeWayList**）→ 确认 → create-order。

## cancel-order（取消订单）

参数：orderId（必填）+ cancelReasonCode（必填，默认 "1"=改主意了；展示原因选项让用户选）。先 query-order 展示订单确认是用户要取消的那单。

## mall-create-order（积分商城兑换）

参数：**skuId+spuCategory 必填**（实测 schema，非旧文档的 shopId）——skuId 来自 mall-product-detail 的具体 SKU；spuCategory："1"虚拟商品/"2"实体（实体必填 addressId）；count 数量。**多商品必须分单**（一商品一订单）。

## draw-lottery（积分抽奖，原子扣积分）

无必填参数，但**必须先调 query-lottery-info** 并向用户展示 drawDecision.nextConsumption（"本次将消耗 24 积分"）→ 用户确认 → 执行。

## auto-bind-coupons（一键领取全部可领券）

无参数。先展示 available-coupons 可领清单 → 用户说"领" → 执行。

## delivery-create-address（新建配送地址）

必填：address/addressDetail/city/contactName/phone（11 位纯数字）；gender 可选。逐字段向用户确认后构造。

## 失败处理（全部写操作）

失败时把服务端报错**原文**给用户（含 code/message/traceId），加一句人话解释，绝不重试写操作、绝不静默吞错；订单清单保留在对话里，指引用户去麦当劳 APP/小程序完成。
