# 实时查询工具速查（全部 2026-10-09 真实调用验证；调用方式按 SKILL.md 三优先级：宿主原生 MCP 直调或 mcp_client.py 脚本）

| 工具 | 必填参数 | 返回结构要点（实测） | 时机 |
|---|---|---|---|
| query-nearby-stores | beType+searchType（=2 时 city 必填） | data[]：storeCode/storeName/address/businessStatus/营业时间/reservation | 会话内无门店时；打烊(60003)→换区域搜 businessStatus=true |
| query-store-coupons | storeCode+orderType+beType | data[]：title/couponId/productCode/有效期；productCode 与菜单 code 同格式可匹配购物车 | 每次出单（比价主力） |
| query-my-coupons | 无（page/pageSize 可选） | **Markdown 文本**：券名/用券价/有效期/**"今日到期"等标签**/到店或外送专用 | 用户问"我有什么券" |
| query-my-account | 无 | availablePoint 可用/accumulativePoint 累计/expiredPoint 已过期/currentMouthExpirePoint 本月将过期 | 每次出单（积分比价）+临期提示 |
| mall-points-products | 无（catRuleIds 类目筛选可选） | data[]：spuName/spuId/point 所需积分/shopId/price 现价/catName | 出单+积分足够时 |
| mall-product-detail | spuId | SKU 规格信息（用户选具体 SKU 后才能 mall-create-order） | 候选商品详情 |
| calculate-price | storeCode+orderType+beType+items | items 用 **productCode**（传 code 会被忽略得 0！）；支持 couponId 券后实算、modification 特制；价格单位**分**；takeWayList（到店下单必用） | 每次出单 |
| query-meal-detail | storeCode+orderType+beType+code | modification.items：特制选项（code/name/maxQuantity/selectedKey，如酱料增减）；rounds：套餐子项 | 用户提定制（"不要辣/换组成"） |
| order-list | 无 | 无历史订单时返回 {}；有则订单列表 | "上次那单"本地无记录时兜底/月度对账 |
| query-order | orderId | 订单详情/状态/配送进度 | 用户问订单状态/提供订单号 |
| query-survey-coupon | orderId | 满意度答卷+关联奖券核销状态 | 用户问满意度/奖券 |
| mall-order-list | 无（size/lastId） | {hasNext, list[]} 商城订单 | 用户问积分兑换订单 |
| mall-order-detail | orderId | 商城订单详情（凭证引导官方 APP） | 同上 |
| delivery-query-addresses | 无 | {addresses[]}：addressId/contactName/脱敏 phone/fullAddress | 外送（会话无地址时） |
| delivery-query-stores | beType(2/6)+addressId | 可配送门店列表 | 外送选店 |
| query-lottery-info | 无 | drawPoint 24 分/次/availablePoint/**drawDecision.nextConsumption**（"本次将消耗 X 积分"） | 用户问抽奖；抽奖确认门的展示素材 |
| query-my-prizes | 无（分页） | {prizes[]} 可用/已过期奖品 | 用户问奖品 |
| campaign-calendar | 无（specifiedDate 可选） | **Markdown**：按日期列活动（标题/内容/图） | 活动问答【有快照，勿调】 |
| available-coupons | 无 | **Markdown**：可领券列表 | 券少时补查【有快照】 |
| now-time-info | 无 | formatted/datetime/timezone（服务器时间） | 本地时钟异常时校时 |
