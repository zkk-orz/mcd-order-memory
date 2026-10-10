#!/usr/bin/env python3
"""作者侧快照管线（L0 数据生成器）：真实调用麦当劳 MCP 拉公开数据写入 assets/。

用法（作者侧执行，需环境变量 MCD_MCP_TOKEN）：
  python scripts/snapshot.py --city 北京市 --keyword 王府井

生成：
  assets/menu-snapshot.json       到店菜单（基准门店；query-meals orderType=1 beType=1）
  assets/nutrition.json           160 项营养表（list-nutrition-foods）
  assets/activities.json          当月营销活动日历（campaign-calendar）
  assets/available-coupons.json   麦麦省可领券清单（available-coupons；若需登录态失败则跳过）

注意：本脚本只在作者侧跑，Token 只从环境变量读；生成物是公开数据（菜单/营养/活动），
不含任何个人信息。快照文件头带 _snapshot 元数据（日期/门店）——L0 输出价格时必须引用该日期。
"""
import argparse
import json
import os
import sys
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from mcp_client import _post, extract_payload  # noqa: E402

ASSETS = Path(__file__).parent.parent / "assets"


def call(tool, arguments, token):
    result = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                    "params": {"name": tool, "arguments": arguments}}, token)
    text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
    return extract_payload(text)


def write_asset(name, payload, note):
    ASSETS.mkdir(parents=True, exist_ok=True)
    doc = {"_snapshot": {"date": datetime.now().strftime("%Y-%m-%d"), "note": note}, "data": payload}
    path = ASSETS / name
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"OK {name} ({path.stat().st_size} bytes)")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True, help="基准门店城市，如 北京市")
    ap.add_argument("--keyword", required=True, help="基准门店关键词，如 王府井")
    args = ap.parse_args()

    token = os.environ.get("MCD_MCP_TOKEN", "")
    if not token:
        print("缺环境变量 MCD_MCP_TOKEN"); sys.exit(1)

    # 1) 基准门店（必填 beType+searchType；searchType=2 按位置搜索时 city 必填）
    stores = call("query-nearby-stores", {"beType": 1, "searchType": 2, "city": args.city, "keyword": args.keyword}, token)
    store = stores[0] if isinstance(stores, list) else stores
    store_code, store_name = store["storeCode"], store["storeName"]
    print(f"基准门店: {store_name} ({store_code})")

    # 2) 到店菜单
    meals = call("query-meals", {"storeCode": store_code, "orderType": 1, "beType": 1}, token)
    write_asset("menu-snapshot.json", meals, f"基准门店 {store_name}；到店自取（orderType=1, beType=1）；不同门店供应或有差异")

    # 3) 营养表
    nutrition = call("list-nutrition-foods", {}, token)
    write_asset("nutrition.json", nutrition, "list-nutrition-foods 全量；营养表相对静态")

    # 4) 活动日历
    cal = call("campaign-calendar", {}, token)
    write_asset("activities.json", cal, "campaign-calendar 当月；月度更新")

    # 5) 可领券（可能要求登录态，失败不阻塞）
    try:
        coupons = call("available-coupons", {}, token)
        write_asset("available-coupons.json", coupons, "available-coupons 麦麦省可领清单；时效性强，仅作参考")
    except Exception as e:  # noqa: BLE001
        print(f"SKIP available-coupons: {e}")

    # 6) 构建 index.json（菜单×营养合并索引——AI 出单冷启动只读它）
    sys.path.insert(0, str(Path(__file__).parent))
    from build_index import main as build_index_main  # noqa: E402
    build_index_main()


if __name__ == "__main__":
    main()
