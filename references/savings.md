# 省钱检查与写操作确认门

## 出单自动省钱检查（用户裁决的核心能力）

**触发**：购买意向确定即自动执行，不询问、不加对话轮次；用户主动问优惠也响应。

**并行包**（实时数据源，三个工具一次并发，用户等待≈最慢一个）：

| 工具 | 用途 | 要点 |
|---|---|---|
| `query-store-coupons` | **比价主力**：当前门店+订单类型可用的券 | 需 storeCode+orderType+beType（实测确认）；返回 title/couponId/productCode/有效期，productCode 与菜单 code 同格式可直接匹配购物车 → 候选方案 B |
| `query-my-account` | 积分余额+临期积分 | **临近过期积分优先提示**（过期=净损失） |
| `mall-points-products` | 积分可兑商品清单 | 类目筛餐品券优先；只对用户感兴趣的 1-2 个候选调 `mall-product-detail`，不批量 |

**关键区分**：`query-store-coupons`（当前单可用，比价用）≠ `query-my-coupons`（卡包资产，不承诺适用当前单；仅用户问"我有什么券"时用）。

**券后价实算（比官方文案更准，实测可行）**：`query-store-coupons` 拿到券后，将 **couponId 传入 calculate-price 的 items**（`{"productCode":..., "quantity":1, "couponId": "..."}`）直接算出券后实付——不要靠"满 X 减 Y"文案自己算，以算价结果为准。券与购物车不匹配时（如只有麦旋风券而购物车是汉堡套餐）**诚实呈现"当前无匹配券"**，不硬凑。

**降级**：任一工具失败**不阻塞出单**——按原价出单+提示"优惠查询失败，可稍后重查"。

**呈现**（告知不代选，选定权在用户）：

```
💰 省钱方案（自动查询）
A 原价 86 元
B 用「满 59 减 15 券」71 元（省 15）
C 积分 1800 兑麦乐鸡 + 付 61 元（省 25，剩 3200 分）
选哪个？（你来定）
```

## 积分兑换比价子流程

1. （已有）积分余额 + 可兑清单；
2. 对候选 SKU 调 `mall-product-detail` 拿所需积分；
3. 本地比价：所需积分 vs 现价（快照价或 calculate-price），换算"每千积分≈X 元"给用户直觉；
4. 用户确认兑换 → `mall-create-order`（shopId=2，**单品单订单**，多商品分单）。

## 领券

- `available-coupons`【有快照】展示可领清单；
- 用户说"领" → `auto-bind-coupons`（**写操作，确认门**）。

## 写操作确认门（四道闸，绝不自动执行）

适用：create-order / cancel-order / mall-create-order / draw-lottery / auto-bind-coupons / delivery-create-address。

1. **预览**：完整清单+实付价+门店+取餐方式（价格来自 calculate-price）；
2. **明确确认词**：等用户说"确认/下单/就这么点"——模糊表达（"行吧""看着办"）要追问一句明确词；
3. **执行回报**：成功回报订单号与关键信息；
4. **失败原文回报**：报错原文+人话解释，保留清单供用户去官方渠道（APP/小程序）完成。

抽奖 `draw-lottery`：先展示 `query-lottery-info` 的消耗规则与 drawDecision → 用户确认 → 执行。
首次启用：检测到 MCD_MCP_TOKEN 时问一次"是否启用真实下单？"记住答案（问 memory 场景一致：听来的，不再问第二遍）。

## 会员价警示（实测坑，来自第一轮验证）

麦金卡商品菜单标会员价（如 32 元）、calculate-price 返回标准价（如 58.5 元）——**单项价格以 calculate-price 为权威**；菜单价与算价差异大的商品在清单中标"⚠️ 会员价商品，结算价以实付为准"。
