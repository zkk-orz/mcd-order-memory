#!/usr/bin/env python3
"""点餐记忆存取（零依赖；数据存 ~/.mcd-order-memory/，skill 无状态、升级不丢数据）。

命令（供 AI 调用，输出 JSON）：
  record  --json '<订单json>'                     记一单（悄悄记，无需用户确认）
  query   --name 娃 [--slot 午餐] [--days 30]     查某人画像（跨餐段聚合或指定餐段）
  people                                           列出所有主体名+别名
  ledger  [--month 2026-10]                        月账单（单列表+合计+省钱战绩）
  settle  --ts "<时间戳>" --name 娃 | --all        AA 销账（"张三付了/都收齐了"）
  debts   [--name 张三]                            查欠款（跨单累计，出单前提示用）
  report  [--month 2026-10]                        月度战报卡（可分享文本，默认脱敏）
  forget  --name 娃 [--match 薯条]                 删除：--match 删匹配条目，无 --match 删整个人

record --json 结构（ts 可省=当前时间）：
  {"ts": "...", "slot": "午餐", "occasion": "部门午餐",
   "people": [{"name": "娃", "items": ["麦乐鸡 5 块"], "constraints": ["不吃酸黄瓜"], "feedback": null}],
   "prices": {"total": 71.0, "paid": 55.0},
   "calories": {"娃": 380},
   "settlement": {"shares": {"娃": 12.5, "妈": 13.0}, "note": "本周五前"}}

settlement 由 order_helper.py aa 命令的 settlement_shares 生成：paid=优惠后实付总额，
shares=每人应付（已按原价比例分摊+取整+差额归发起人）。销账只改状态，绝不为用户发起收款或催收。
"""
import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

DATA_DIR = Path.home() / ".mcd-order-memory"
ORDERS_FILE = DATA_DIR / "orders.json"
ALIASES_FILE = DATA_DIR / "aliases.json"

REPO_URL = "github.com/zkk-orz/mcd-order-memory"
# 趣味换算基准：营养快照"麦乐鸡5块 = 213 kcal"→ 每块 42.6
NUGGET_KCAL = 213 / 5


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
    # 同 ts 覆盖（upsert）：单子状态变化（定稿/付款/报销/换品项）用同一 ts 重记，
    # 覆盖旧记录而非追加——防"一单被记 4 次"的台账虚高（WorkBuddy 实测教训）
    updated = False
    for i, o in enumerate(orders):
        if o.get("ts") == order["ts"]:
            orders[i] = order
            updated = True
            break
    if not updated:
        orders.append(order)
    _save(ORDERS_FILE, orders)
    # 别名归一提示：同名不同写不在此处合并，由 AI 判断后写 aliases
    print(json.dumps({"ok": True, "recorded": order["ts"], "updated": updated,
                      "people": [p.get("name") for p in order["people"]] or [order["occasion"]]}, ensure_ascii=False))


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


def _pr_total(pr):
    return pr.get("total") or 0.0


def _pr_paid(pr):
    # paid 显式为 null 时 .get 不走默认值（dict 语义），必须显式判 None（WorkBuddy 实测崩溃点）
    p = pr.get("paid")
    return p if p is not None else _pr_total(pr)


def cmd_ledger(args):
    month = args.month or datetime.now().strftime("%Y-%m")
    rows, total, paid = [], 0.0, 0.0
    for o in _load(ORDERS_FILE, []):
        if not o.get("ts", "").startswith(month):
            continue
        pr = o.get("prices") or {}
        t, p = _pr_total(pr), _pr_paid(pr)
        total += t
        paid += p
        rows.append({"ts": o.get("ts", ""), "slot": o.get("slot", ""), "who": [p2.get("name") for p2 in o.get("people", [])] or [o.get("occasion")],
                     "total": t, "paid": p})
    print(json.dumps({"month": month, "orders": len(rows), "total": round(total, 2),
                      "paid": round(paid, 2), "saved": round(total - paid, 2), "rows": rows}, ensure_ascii=False, indent=1))


def cmd_settle(args):
    orders = _load(ORDERS_FILE, [])
    hit = next((o for o in orders if o.get("ts") == args.ts), None)
    if hit is None:
        print(json.dumps({"ok": False, "error": f"未找到该时间戳的单：{args.ts}"}, ensure_ascii=False)); sys.exit(1)
    st = hit.get("settlement")
    if not st or not st.get("shares"):
        print(json.dumps({"ok": False, "error": "该单没有分账记录——先以同一 ts record 带 settlement"
                          "（order_helper.py aa 输出的 settlement 结构），再销账"}, ensure_ascii=False)); sys.exit(1)
    paid_map = st.setdefault("paid", {})
    if args.all:
        paid_map.update({n: True for n in st["shares"]})
        who = list(st["shares"])
    else:
        name = _resolve(args.name)
        if name not in st["shares"]:
            print(json.dumps({"ok": False, "error": f"{name} 不在这单的分账名单里",
                              "shares": st["shares"]}, ensure_ascii=False)); sys.exit(1)
        paid_map[name] = True
        who = [name]
    _save(ORDERS_FILE, orders)
    remaining = [n for n in st["shares"] if not st["paid"].get(n)]
    print(json.dumps({"ok": True, "settled": who, "ts": args.ts,
                      "remaining": remaining}, ensure_ascii=False))


def cmd_debts(args):
    name = _resolve(args.name) if args.name else None
    debts = {}
    for o in _load(ORDERS_FILE, []):
        st = o.get("settlement") or {}
        for n, amt in (st.get("shares") or {}).items():
            if (st.get("paid") or {}).get(n):
                continue
            n2 = _resolve(n)
            if name and n2 != name:
                continue
            debts.setdefault(n2, []).append({"ts": o.get("ts", ""), "slot": o.get("slot", ""),
                                             "occasion": o.get("occasion", ""), "amount": amt})
    summary = {n: round(sum(x["amount"] for x in rows), 2) for n, rows in debts.items()}
    print(json.dumps({"name": name, "debts": {n: {"total": summary[n], "orders": rows} for n, rows in debts.items()},
                      "grand_total": round(sum(summary.values()), 2)}, ensure_ascii=False, indent=1))


def cmd_report(args):
    month = args.month or datetime.now().strftime("%Y-%m")
    rows = [o for o in _load(ORDERS_FILE, []) if o.get("ts", "").startswith(month)]
    total = paid = 0.0
    people, item_freq, total_kcal = set(), {}, 0
    for o in rows:
        pr = o.get("prices") or {}
        total += _pr_total(pr)
        paid += _pr_paid(pr)
        for p in o.get("people", []):
            people.add(p.get("name", "?"))
            for it in p.get("items", []):
                item_freq[it] = item_freq.get(it, 0) + 1
        total_kcal += sum((o.get("calories") or {}).values())
    saved = round(total - paid, 2)
    top = max(item_freq, key=item_freq.get) if item_freq else None
    n_people = max(1, len(people))
    nuggets = round(total_kcal / n_people / NUGGET_KCAL) if total_kcal else None
    lines = [f"🍔 本群麦门月报 · {month}"]
    if not rows:
        lines.append("本月还没有记录——点过一单再来生成：）")
    else:
        lines.append(f"本月接龙 {len(rows)} 次 · 服务 {len(people)} 人 · 合计 {total:g} 元")
        if saved > 0:
            lines.append(f"共省 {saved:g} 元（券+积分+会员价，与账单逐笔可对账）")
        if top:
            lines.append(f"本群最爱：{top}（出现 {item_freq[top]} 次）")
        if nuggets:
            lines.append(f"人均热量 ≈ {nuggets} 块麦乐鸡 🍗")
    lines.append(f"—— 由 mcd-order-memory 生成 · {REPO_URL}")
    # 脱敏纪律：卡片只含数字与最高频单品，人名与忌口一律不进卡
    print(json.dumps({"month": month, "orders": len(rows), "people": len(people),
                      "total": round(total, 2), "paid": round(paid, 2), "saved": saved,
                      "top_item": {"name": top, "count": item_freq.get(top)} if top else None,
                      "total_kcal": total_kcal, "nuggets_per_person": nuggets,
                      "card": "\n".join(lines)}, ensure_ascii=False, indent=1))


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
    st = sub.add_parser("settle"); st.add_argument("--ts", required=True)
    st.add_argument("--name"); st.add_argument("--all", action="store_true"); st.set_defaults(fn=cmd_settle)
    dbt = sub.add_parser("debts"); dbt.add_argument("--name"); dbt.set_defaults(fn=cmd_debts)
    rep = sub.add_parser("report"); rep.add_argument("--month"); rep.set_defaults(fn=cmd_report)
    f = sub.add_parser("forget"); f.add_argument("--name", required=True); f.add_argument("--match"); f.set_defaults(fn=cmd_forget)
    args = ap.parse_args()
    try:
        args.fn(args)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败: {e}"}, ensure_ascii=False)); sys.exit(1)


if __name__ == "__main__":
    main()
