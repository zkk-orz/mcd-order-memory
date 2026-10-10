#!/usr/bin/env python3
"""订单速算器（用户侧，零依赖）：AI 解析完"人→品项"后，调本脚本一次拿到全表。

用法：
  python scripts/order_helper.py quote --json '{
    "slot": "午餐",
    "people": [{"name": "张三", "items": ["双吉套餐"]},
               {"name": "李四", "items": ["板烧鸡腿堡"]},
               {"name": "王五", "items": ["1+1可乐"]}] }'

输出 JSON：每人每项的价格/卡路里/匹配方式、合计、人均（AA）；未匹配项列入 unmatched 交给 AI 追问。
匹配顺序：精确品名 → 别名（含"品名+补充词"如 1+1可乐）→ 包含匹配。
"""
import argparse
import json
import re
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"


def load_index():
    doc = json.loads((ASSETS / "index.json").read_text(encoding="utf-8"))
    return doc["items"], doc["_snapshot"]["date"]


def match(item_text: str, items: list):
    """口语品项 → index 条目。支持'别名+修饰词'（1+1可乐 → 人气经典随心配 + 备注可乐）。"""
    t = item_text.strip().lower()
    # 精确名
    for it in items:
        if t == it["name"].lower():
            return it, None
    # 别名（取最长命中，允许后面跟修饰词）
    best = None
    for it in items:
        for alias in [it["name"], *it["aliases"]]:
            a = alias.lower()
            if a and a in t:
                if best is None or len(a) > len(best[0]):
                    best = (a, it)
    if best:
        it = best[1]
        extra = t.replace(best[0], "").strip(" +，,、")
        return it, (extra or None)
    # 包含匹配（菜单名含在口语里或反之）
    for it in items:
        n = it["name"].lower()
        if n in t or t in n:
            return it, None
    return None, None


def cmd_quote(args):
    order = json.loads(args.json)
    items, snap_date = load_index()
    people_out, unmatched, total = [], [], 0.0
    for p in order.get("people", []):
        row = {"name": p["name"], "items": []}
        for text in p.get("items", []):
            it, extra = match(text, items)
            if it is None:
                unmatched.append({"who": p["name"], "text": text})
                continue
            note = []
            if it["kcal_note"]:
                note.append(it["kcal_note"])
            if extra:
                note.append(f"修饰词'{extra}'由对话确认")
            row["items"].append({"asked": text, "name": it["name"], "code": it["code"],
                                 "price": it["price"], "kcal": it["kcal"], "note": "；".join(note) or None})
            total += it["price"]
        kcal = sum(i["kcal"] or 0 for i in row["items"])
        row["kcal_total"] = kcal if kcal else None
        people_out.append(row)
    n = max(1, len(people_out))
    print(json.dumps({"ok": not unmatched, "slot": order.get("slot", ""), "snapshot_date": snap_date,
                      "people": people_out, "total": round(total, 2), "per_person": round(total / n, 2),
                      "unmatched": unmatched}, ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    q = ap.add_subparsers(dest="cmd", required=True)
    sp = q.add_parser("quote"); sp.add_argument("--json", required=True); sp.set_defaults(fn=cmd_quote)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
