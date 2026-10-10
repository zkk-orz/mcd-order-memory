# MCP_INTEGRATION.md — 麦当劳 MCP 使用说明

## Server 与认证

- **Server**：麦当劳中国官方 MCP Server，`https://mcp.mcd.cn`，Streamable HTTP（无状态）
- **认证**：Bearer Token，从环境变量 `MCD_MCP_TOKEN` 读取（[open.mcd.cn](https://open.mcd.cn) 免费申请）
- **工具总数**：35 个（README 记载 33 + 未记载的 query-promotions/query-survey-coupon）；本 skill 使用 **30 个**，不使用生日会/派对 5 个
- **调用实现**：`scripts/mcp_client.py`（Python 标准库 urllib，零依赖；SSE 响应解析 + 内嵌业务 JSON 提取）

## 使用方式：双层数据策略（使用者负担铁律）

**L0 快照层（零配置）**：作者侧用 `scripts/snapshot.py` 定期真实调用 MCP 拉公开数据固化为 `assets/`（菜单 15 类 126 品/营养 160 项/活动日历/可领券清单，文件头含快照日期）——**skill 参赛作品真实使用麦当劳 MCP 能力**由此管线与 L1 实时层共同满足。

**L1 实时层（一个环境变量）**：运行时经 `mcp_client.py` 直连，用于实时价格、私有数据（券/积分/订单/地址）与写操作。

## 工具使用与业务价值（30 个）

### 配餐与算价（核心链路，✅ 实测）

| 工具 | 用途 | 业务价值 |
|---|---|---|
| query-nearby-stores | 找店（必填 beType+searchType） | 深夜自动换营业门店（实测 60003 打烊→换 24h 店） |
| query-meals | 菜单（快照+实时） | 配餐避忌口、官方团餐搭配规则内嵌 |
| query-meal-detail | 餐品特制选项 | "不要辣/换酱料"的官方定制（实测 modification 结构） |
| calculate-price | 实时算价 | items 用 productCode（实测）；**券后价实算**（couponId 直传）；takeWayList 供下单 |
| list-nutrition-foods | 160 项营养表 | 每人每餐卡路里、月度累计纠偏 |

### 省钱比价（✅ 实测）

| 工具 | 用途 |
|---|---|
| query-store-coupons | 当前门店可用券（比价主力；productCode 与菜单 code 匹配购物车） |
| query-my-coupons | 卡包资产（Markdown，"今日到期"标签） |
| query-my-account | 积分余额/临期（实测 availablePoint/expiredPoint 字段） |
| mall-points-products / mall-product-detail | 积分可兑商品与 SKU |
| available-coupons / campaign-calendar | 可领券与活动日历（L0 快照源） |

### 订单与外送（查询 ✅ 实测；写操作为 schema 级实现，未经真实交易验证）

| 工具 | 状态 | 说明 |
|---|---|---|
| order-list / query-order / query-survey-coupon | ✅ 实测 | 历史对账/订单跟踪/满意度奖券 |
| mall-order-list / mall-order-detail | ✅ 实测 | 商城订单 |
| delivery-query-addresses / delivery-query-stores | ✅ 实测 | 外送地址（脱敏手机号）→可送门店 |
| now-time-info | ✅ 实测 | 服务器校时（餐段推断兜底） |
| create-order / cancel-order | ⚠️ schema 级 | 真实下单/取消——**四道闸**（预览→确认词→`--i-confirm` 脚本强制→失败原文回报）；takeWayCode 取自 calculate-price |
| mall-create-order | ⚠️ schema 级 | 积分兑换（实测 schema：skuId+spuCategory） |
| auto-bind-coupons / draw-lottery / delivery-create-address | ⚠️ schema 级 | 领券/抽奖（先展示 query-lottery-info 消耗规则）/建地址，均走确认门 |

### 团餐与抽奖查询（✅ 探查/query 侧）

query-promotions / query-meal-assistance（企业团餐 beType=6 通道：满减规则+助餐服务，gmServiceCode 供 create-order）——按 schema 实现，未做团餐场景实测（参赛开发期决策：不产生真实团餐交易）。

## 真实调用流程示例（2026-10-09 实测）

```
1. query-nearby-stores {"beType":1,"searchType":2,"city":"北京市","keyword":"王府井"}
   → 深夜打烊(60003) → 换区域 → 团结湖店(1950050, 00:00-23:59, businessStatus=true)
2. query-store-coupons {"storeCode":"1950050","orderType":1,"beType":1}
   → 麦旋风任选/薯薯任选（与购物车不匹配→诚实呈现不硬凑）
3. query-my-account {} → 可用 188.4 分（不足兑换，如实呈现）
4. calculate-price {"storeCode":"1950050","orderType":1,"beType":1,
   "items":[{"productCode":"9900005464","quantity":1},{"productCode":"1440","quantity":1},
            {"productCode":"9900013304","quantity":1}]}
   → price: 7140（分）= 71.4 元，与菜单快照价 34+22.5+14.9 双源一致 ✓
```

## 诚实声明

- 上述标注 ✅ 的工具均于 2026-10-09 使用真实 Token 逐一调用验证（只读查询）；
- 标注 ⚠️ 的 6 个写操作按官方 inputSchema 实现，**未经真实交易验证**（参赛开发期不产生真实扣费交易）；执行侧有脚本级强制确认门（`mcp_client.py` 缺 `--i-confirm` 直接拒绝，实测拦截有效）；
- 本仓库不含真实 Token；`mcp-config.example.json` 仅环境变量占位符。
