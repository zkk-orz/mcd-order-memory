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


_HTML_TMPL = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>麦门月报 · {month}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: "PingFang SC", "Microsoft YaHei", -apple-system, sans-serif;
         background: #fff8f0; color: #2b2b2b; padding: 28px 16px 48px; line-height: 1.6; }}
  .wrap {{ max-width: 760px; margin: 0 auto; }}
  .hero {{ background: linear-gradient(135deg, #DA291C 0%, #e0412f 100%); border-radius: 20px;
          padding: 30px 28px; color: #fff; box-shadow: 0 10px 30px rgba(218,41,28,.25);
          position: relative; overflow: hidden; }}
  .hero::after {{ content: "🍔"; position: absolute; right: -10px; top: -20px;
                 font-size: 140px; opacity: .12; transform: rotate(-12deg); }}
  .hero .kicker {{ font-size: 14px; letter-spacing: 3px; opacity: .9; }}
  .hero h1 {{ font-size: 34px; margin: 6px 0 4px; font-weight: 800; }}
  .hero .sub {{ font-size: 14px; opacity: .92; }}
  .stats {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; margin: 20px 0; }}
  .stat {{ background: #fff; border: 2px solid #ffd9a8; border-radius: 16px; padding: 16px 10px;
          text-align: center; box-shadow: 0 4px 14px rgba(218,41,28,.06); }}
  .stat .num {{ font-size: 26px; font-weight: 800; color: #DA291C; }}
  .stat .lbl {{ font-size: 13px; color: #8a6a4a; margin-top: 2px; }}
  .sec {{ background: #fff; border-radius: 18px; padding: 22px 24px; margin: 18px 0;
         box-shadow: 0 4px 16px rgba(0,0,0,.05); }}
  .sec h2 {{ font-size: 19px; color: #DA291C; margin-bottom: 14px; display: flex; align-items: center; gap: 8px; }}
  .sec h2::before {{ content: ""; width: 6px; height: 20px; background: #FFC72C; border-radius: 3px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ padding: 11px 10px; text-align: left; border-bottom: 1px solid #f0e4d4; }}
  th {{ color: #a06a2c; font-weight: 700; font-size: 12.5px; }}
  .pill {{ display: inline-block; padding: 2px 9px; border-radius: 20px; font-size: 12px; font-weight: 700; }}
  .pill.paid {{ background: #e7f7ec; color: #1f8a43; }}
  .pill.due {{ background: #fff3d6; color: #b8801a; }}
  .price {{ color: #DA291C; font-weight: 800; }}
  .note {{ background: #fff8e8; border-left: 4px solid #FFC72C; padding: 12px 16px;
          border-radius: 8px; font-size: 14px; color: #7a5a2a; }}
  .footer {{ text-align: center; font-size: 12px; color: #b09a82; margin-top: 26px; }}
</style>
</head>
<body>
<div class="wrap">
  <div class="hero">
    <div class="kicker">MCD ORDER MEMORY</div>
    <h1>🍔 本群麦门月报</h1>
    <div class="sub">{month} · {orders} 次接龙 · 服务 {people} 人{debt_note}</div>
  </div>
  <div class="stats">
    <div class="stat"><div class="num">{total:g}<small> 元</small></div><div class="lbl">合计消费</div></div>
    <div class="stat"><div class="num">{saved:g}<small> 元</small></div><div class="lbl">共省（券+积分+会员价）</div></div>
    <div class="stat"><div class="num">{nuggets}<small> 块</small></div><div class="lbl">人均热量 ≈ 麦乐鸡</div></div>
    <div class="stat"><div class="num">{orders}</div><div class="lbl">本月单数</div></div>
  </div>
  <div class="sec">
    <h2>本群最爱</h2>
    <div class="note">{top_line}</div>
  </div>{names_sec}
  <div class="footer">—— 由 <b>mcd-order-memory</b> 生成 · 数字与账单逐笔可对账 · {REPO_URL}</div>
</div>
</body>
</html>
"""


def _write_html(month, agg, detail, show_names):
    """生成网页版战报（本地文件，不联网）。默认脱敏：人名不进页面；--names 才带个人战绩表。"""
    names_sec = ""
    if show_names and detail:
        rows_html = "".join(
            f"<tr><td>{d['name']}</td><td>{'、'.join(d['items'])}</td>"
            f"<td class='price'>{d['amount']:g} 元</td>"
            f"<td><span class='pill {'paid' if d['paid'] else 'due'}'>"
            f"{'已结清' if d['paid'] else '待收'}</span></td></tr>"
            for d in detail)
        names_sec = (f"\n  <div class=\"sec\">\n    <h2>战绩表</h2>\n"
                     f"    <table><tr><th>成员</th><th>常点</th><th>本月应付</th><th>状态</th></tr>"
                     f"{rows_html}</table>\n  </div>")
    debt_note = ""
    if agg.get("debt_total"):
        debt_note = f" · 待收 {agg['debt_total']:g} 元"
    top_line = (f"{agg['top_item']['name']}（出现 {agg['top_item']['count']} 次）"
                if agg["top_item"] else "本月还没有记录——点过一单再来生成：）")
    html = _HTML_TMPL.format(month=month, orders=agg["orders"], people=agg["people"],
                             total=agg["total"], saved=max(agg["saved"], 0),
                             nuggets=agg["nuggets_per_person"] or 0, top_line=top_line,
                             names_sec=names_sec, debt_note=debt_note, REPO_URL=REPO_URL)
    path = Path(f"mcd-report-{month}.html")
    path.write_text(html, encoding="utf-8")
    return str(path)


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
    # 个人明细（仅 --names 用于 HTML 战绩表；文本卡与默认 HTML 均不进人名——脱敏纪律）
    detail = {}
    for o in rows:
        st = o.get("settlement") or {}
        for p in o.get("people", []):
            n = p.get("name", "?")
            d = detail.setdefault(n, {"name": n, "items": [], "amount": 0.0, "paid": True})
            d["items"].extend(p.get("items", []))
            amt = (st.get("shares") or {}).get(n)
            if amt is not None:
                d["amount"] = round(d["amount"] + amt, 2)
                if not (st.get("paid") or {}).get(n):
                    d["paid"] = False
    debt_total = round(sum(d["amount"] for d in detail.values() if not d["paid"]), 2)
    detail = sorted(detail.values(), key=lambda d: -d["amount"])
    # 常点只显示频次 top3，避免长尾刷屏
    for d in detail:
        cnt = {}
        for it in d["items"]:
            cnt[it] = cnt.get(it, 0) + 1
        d["items"] = [i for i, _ in sorted(cnt.items(), key=lambda kv: -kv[1])[:3]]
    agg = {"orders": len(rows), "people": len(people), "total": round(total, 2),
           "saved": saved, "top_item": {"name": top, "count": item_freq.get(top)} if top else None,
           "nuggets_per_person": nuggets, "debt_total": debt_total or None}
    out = {"month": month, **agg, "paid": round(paid, 2),
           "total_kcal": total_kcal, "card": "\n".join(lines)}
    if args.html:
        out["html_path"] = _write_html(month, agg, detail, show_names=args.names)
        out["html_note"] = "默认脱敏（无人名）" + ("，已含战绩表（--names）" if args.names else "；加 --names 可含个人战绩表")
    # 脱敏纪律：卡片只含数字与最高频单品，人名与忌口一律不进卡
    print(json.dumps(out, ensure_ascii=False, indent=1))


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
    rep = sub.add_parser("report"); rep.add_argument("--month")
    rep.add_argument("--html", action="store_true", help="同时生成网页版战报 mcd-report-<月>.html（本地文件）")
    rep.add_argument("--names", action="store_true", help="网页版含个人战绩表（默认脱敏不进人名）")
    rep.set_defaults(fn=cmd_report)
    f = sub.add_parser("forget"); f.add_argument("--name", required=True); f.add_argument("--match"); f.set_defaults(fn=cmd_forget)
    args = ap.parse_args()
    try:
        args.fn(args)
    except json.JSONDecodeError as e:
        print(json.dumps({"ok": False, "error": f"JSON 解析失败: {e}"}, ensure_ascii=False)); sys.exit(1)


if __name__ == "__main__":
    main()
