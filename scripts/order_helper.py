#!/usr/bin/env python3
"""订单速算器（用户侧，零依赖）：AI 解析完"人→品项"后，调本脚本一次拿到全表。

用法：
  python scripts/order_helper.py quote --json '{
    "slot": "午餐",
    "people": [{"name": "张三", "items": ["双吉套餐"]},
               {"name": "李四", "items": ["板烧鸡腿堡"]},
               {"name": "王五", "items": ["1+1可乐"]}] }'

输出 JSON：每人每项的价格/卡路里/匹配方式、个人小计、合计、人均（AA）；未匹配项列入 unmatched 交给 AI 追问。
匹配顺序：精确品名 → 别名（含"品名+补充词"如 1+1可乐）→ 包含匹配。

AA 收款卡（优惠方案选定后，把实付总额按各人原价比例分摊）：
  python scripts/order_helper.py aa --json '{
    "paid": 55.0, "owner": "张三", "deadline": "本周五前",
    "people": [{"name": "张三", "share": 26.5}, {"name": "李四", "share": 28.9}] }'

输出：每人应付（比例分摊+取整+差额归属）、微信群收款"按人填金额"照抄清单、收款说明模板。
只生成文本，不代发不代催——发起收款与催收动作全在用户手里。
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
        row["subtotal"] = round(sum(i["price"] for i in row["items"]), 2)
        people_out.append(row)
    n = max(1, len(people_out))
    print(json.dumps({"ok": not unmatched, "slot": order.get("slot", ""), "snapshot_date": snap_date,
                      "people": people_out, "total": round(total, 2), "per_person": round(total / n, 2),
                      "unmatched": unmatched}, ensure_ascii=False, indent=1))


def _round_to(x, unit):
    return round(round(x / unit) * unit, 2)


def cmd_aa(args):
    """实付总额按各人原价份额比例分摊，取整到 unit，差额归 owner（默认最大份额者）。"""
    cfg = json.loads(args.json)
    paid = float(cfg["paid"])
    unit = float(args.round)
    people = cfg["people"]
    share_sum = sum(p["share"] for p in people)
    if share_sum <= 0:
        print(json.dumps({"ok": False, "error": "shares 全为 0，无法分摊"}, ensure_ascii=False))
        return
    rows = []
    for p in people:
        fair = paid * p["share"] / share_sum
        rows.append({"name": p["name"], "fair": round(fair, 2), "pay": _round_to(fair, unit)})
    diff = round(paid - sum(r["pay"] for r in rows), 2)
    owner = cfg.get("owner") or max(rows, key=lambda r: r["fair"])["name"]
    for r in rows:
        if r["name"] == owner:
            r["pay"] = round(r["pay"] + diff, 2)
            r["absorbs_diff"] = diff != 0
    deadline = cfg.get("deadline", "本周五前")
    slot = cfg.get("slot", "这一餐")
    lines = [f"【{slot}AA】实付 {paid:g} 元，按原价比例摊，麻烦大家 {deadline} 转我，谢谢～"]
    lines.append("微信群收款（按人填金额）逐人照抄：")
    for r in rows:
        if r["name"] == owner:
            lines.append(f"  {r['name']}  {r['pay']:g}（发起人自己的那份，收款名单不用含）")
        else:
            lines.append(f"  {r['name']}  {r['pay']:g}")
    if abs(diff) >= 0.01:
        lines.append(f"（取整差额 {diff:+g} 元已并入 {owner}）")
    print(json.dumps({"ok": True, "paid": paid, "round_unit": unit, "diff": diff, "owner": owner,
                      "pay_list": rows, "note_template": "\n".join(lines[0:1]),
                      "weixin_text": "\n".join(lines), "settlement_shares": {r["name"]: r["pay"] for r in rows}},
                     ensure_ascii=False, indent=1))


def main():
    ap = argparse.ArgumentParser()
    q = ap.add_subparsers(dest="cmd", required=True)
    sp = q.add_parser("quote"); sp.add_argument("--json", required=True); sp.set_defaults(fn=cmd_quote)
    aa = q.add_parser("aa"); aa.add_argument("--json", required=True)
    aa.add_argument("--round", default="0.5", help="取整单位（元），默认 0.5；0.01 为精确到分"); aa.set_defaults(fn=cmd_aa)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
