#!/usr/bin/env python3
"""点餐记忆存取（零依赖；数据存 ~/.mcd-order-memory/，skill 无状态、升级不丢数据）。

命令（供 AI 调用，输出 JSON）：
  record  --json '<订单json>'                     记一单（悄悄记，无需用户确认）
  query   --name 娃 [--slot 午餐] [--days 30]     查某人画像（跨餐段聚合或指定餐段）
  people                                           列出所有主体名+别名
  ledger  [--month 2026-10]                        月账单（单列表+合计+省钱战绩）
  forget  --name 娃 [--match 薯条]                 删除：--match 删匹配条目，无 --match 删整个人

record --json 结构（ts 可省=当前时间）：
  {"ts": "...", "slot": "午餐", "occasion": "部门午餐",
   "people": [{"name": "娃", "items": ["麦乐鸡 5 块"], "constraints": ["不吃酸黄瓜"], "feedback": null}],
   "prices": {"total": 71.0, "paid": 55.0},
   "calories": {"娃": 380}}
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path.home() / ".mcd-order-memory"
ORDERS_FILE = DATA_DIR / "orders.json"
ALIASES_FILE = DATA_DIR / "aliases.json"


def _load(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def _save(path, data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def cmd_record(args):
    order = json.loads(args.json)
    order.setdefault("ts", _now())
    order.setdefault("slot", "")
    order.setdefault("occasion", "")
    order.setdefault("people", [])
    orders = _load(ORDERS_FILE, [])
    orders.append(order)
    _save(ORDERS_FILE, orders)
    # 别名归一提示：同名不同写不在此处合并，由 AI 判断后写 aliases
    print(json.dumps({"ok": True, "recorded": order["ts"], "people": [p.get("name") for p in order["people"]] or [order["occasion"]]}, ensure_ascii=False))


def _resolve(name):
    """别名 → 主体名（aliases.json: {"娃": ["孩子", "儿子"]}）"""
    aliases = _load(ALIASES_FILE, {})
    for canon, alias_list in aliases.items():
        if name == canon or name in alias_list:
            return canon
    return name


def cmd_query(args):
    name = _resolve(args.name)
    days = args.days or 3650
    since = datetime.now() - timedelta(days=days)
    hits = []
    constraints, feedbacks, aliases_seen = set(), set(), set()
    for o in _load(ORDERS_FILE, []):
        try:
            ts = datetime.strptime(o["ts"], "%Y-%m-%d %H:%M:%S")
        except (KeyError, ValueError):
            ts = datetime.now()
        if ts < since:
            continue
        for p in o.get("people", []):
            if p.get("name") == name:
                if args.slot and o.get("slot") != args.slot:
                    continue
                hits.append({"ts": o["ts"], "slot": o.get("slot", ""), "items": p.get("items", []),
                             "calories": o.get("calories", {}).get(name)})
                constraints.update(p.get("constraints") or [])
                feedbacks.update(x for x in [p.get("feedback")] if x)
                aliases_seen.update(p.get("aliases") or [])
    # 各餐段偏好聚合（频次排序）
    slots = {}
    for h in hits:
        for it in h["items"]:
            slots.setdefault(h["slot"], {}).setdefault(it, 0)
            slots[h["slot"]][it] += 1
    profile = {s: sorted(items, key=lambda k: -items[k]) for s, items in slots.items()}
    print(json.dumps({"name": name, "orders": len(hits), "constraints": sorted(constraints),
                      "feedback": sorted(feedbacks), "profile_by_slot": profile, "recent": hits[-10:]},
                     ensure_ascii=False, indent=1))


def cmd_people(args):
    orders = _load(ORDERS_FILE, [])
    names = {}
    for o in orders:
        for p in o.get("people", []):
            names[p.get("name", "?")] = names.get(p.get("name", "?"), 0) + 1
        if o.get("occasion") and not o.get("people"):
            names["#单·" + o["occasion"]] = names.get("#单·" + o["occasion"], 0) + 1
    print(json.dumps({"people": names, "aliases": _load(ALIASES_FILE, {})}, ensure_ascii=False, indent=1))


def cmd_ledger(args):
    month = args.month or datetime.now().strftime("%Y-%m")
    rows, total, paid = [], 0.0, 0.0
    for o in _load(ORDERS_FILE, []):
        if not o["ts"].startswith(month):
            continue
        pr = o.get("prices", {})
        total += pr.get("total", 0.0)
        paid += pr.get("paid", pr.get("total", 0.0))
        rows.append({"ts": o["ts"], "slot": o.get("slot", ""), "who": [p.get("name") for p in o.get("people", [])] or [o.get("occasion")],
                     "total": pr.get("total"), "paid": pr.get("paid", pr.get("total"))})
    print(json.dumps({"month": month, "orders": len(rows), "total": round(total, 2),
                      "paid": round(paid, 2), "saved": round(total - paid, 2), "rows": rows}, ensure_ascii=False, indent=1))


def cmd_forget(args):
    name = _resolve(args.name)
    orders = _load(ORDERS_FILE, [])
    removed_people = 0
    kept_orders = []
    for o in orders:
        people = o.get("people", [])
        stayed = []
        for p in people:
            if p.get("name") == name:
                if args.match:
                    p["items"] = [i for i in p.get("items", []) if args.match not in i]
                    p["constraints"] = [c for c in p.get("constraints", []) if args.match not in c]
                    if p["items"] or p["constraints"] or p.get("feedback"):
                        stayed.append(p)
                    else:
                        removed_people += 1
                else:
                    removed_people += 1
            else:
                stayed.append(p)
        o["people"] = stayed
        if o.get("people") or o.get("occasion"):
            kept_orders.append(o)
    _save(ORDERS_FILE, kept_orders)
    # 删整个人时连别名
    aliases = _load(ALIASES_FILE, {})
    if name in aliases and not args.match:
        del aliases[name]
        _save(ALIASES_FILE, aliases)
    print(json.dumps({"ok": True, "removed": removed_people, "target": name, "match": args.match}, ensure_ascii=False))


def main():
    ap = argparse.ArgumentParser(description="点餐记忆存取")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("--json", required=True); r.set_defaults(fn=cmd_record)
    q = sub.add_parser("query"); q.add_argument("--name", required=True)
    q.add_argument("--slot"); q.add_argument("--days", type=int); q.set_defaults(fn=cmd_query)
    sub.add_parser("people").set_defaults(fn=cmd_people)
    l = sub.add_parser("ledger"); l.add_argument("--month"); l.set_defaults(fn=cmd_ledger)
    f = sub.add_parser("forget"); f.add_argument("--name", required=True); f.add_argument("--match"); f.set_defaults(fn=cmd_forget)
    args = ap.parse_args()
    try:
        args.fn(args)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败: {e}"}, ensure_ascii=False)); sys.exit(1)


if __name__ == "__main__":
    main()
