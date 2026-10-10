#!/usr/bin/env python3
"""作者侧索引构建（snapshot.py 之后自动跑）：把菜单快照×营养表合并成轻量索引 assets/index.json。

目的：AI 出单时只需读这一个文件（几 KB）就能拿到"品名→价格+卡路里"映射，
不必现场解析 48KB 菜单与营养 CSV——首响应从十分钟级降到一次文件读取。

匹配规则：
- 营养表按品名精确/包含匹配菜单品项（如 麦辣鸡腿汉堡→同名行）；
- 套餐无营养行时按组成估算：主品+中薯条+中可乐，kcal 标注"≈估算"；
- 别名：内置常见口语缩写表（双吉/麦辣/板烧/1+1…）+ 名称规则生成（去"汉堡/堡"等后缀）。
"""
import json
import re
from pathlib import Path

ASSETS = Path(__file__).parent.parent / "assets"

# 常见口语别名（作者侧维护，小而精）
ALIASES = {
    "双层吉士汉堡套餐": ["双吉套餐", "双吉"],
    "双层吉士汉堡": ["双吉"],
    "麦辣鸡腿汉堡": ["麦辣", "麦辣鸡腿堡", "麦辣堡"],
    "板烧鸡腿堡": ["板烧", "板烧鸡腿堡"],
    "麦乐鸡": ["麦乐鸡块"],
    "圆筒冰淇淋": ["圆筒", "甜筒"],
    "可乐": ["可口可乐"],
    "人气经典随心配": ["1+1", "1+1随心配", "随心配1+1"],
    "精选超值随心配": ["精选1+1"],
    "巨无霸": ["big mac"],
    "麦旋风": ["mcflurry"],
    "中薯条": ["薯条"],
}


def parse_nutrition(raw: str):
    """营养 CSV 文本 → {品名: kcal}。表头列序：productName,nutritionDescription,energyKj,energyKcal,protein,...（kcal=parts[3]）"""
    table = {}
    for line in raw.splitlines():
        line = line.strip().rstrip(",")
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 4 or not parts[0] or parts[0].startswith("["):
            continue
        try:
            kcal = int(parts[3])
        except ValueError:
            continue
        table[parts[0]] = kcal
    return table


# 营养表未收录时的同类粗估（kcal），一律标"同类估算"
FALLBACK_RULES = [("随心配", 500), ("套餐", 650), ("冰淇淋", 250), ("圆筒", 95),
                 ("可乐", 150), ("咖啡", 120), ("汁", 120), ("奶", 180), ("派", 280)]


def kcal_for(name: str, nutrition: dict):
    """菜单品名 → (kcal, note)。顺序：精确名 → 套餐组成估算（先于包含匹配，避免把套餐当主品单品）→ 包含 → 同类粗估。"""
    if name in nutrition:
        return nutrition[name], None
    m = re.sub(r"(中|大)?(套餐|三件套|四件套)$", "", name)
    if m != name:
        for n, k in nutrition.items():
            if n in m or m in n:
                return k + nutrition.get("中薯条", 289) + nutrition.get("可乐中杯", 147), "套餐按组成估算（主品+中薯+中可乐）"
    for n, k in nutrition.items():
        if n in name or name in n:
            return k, None
    for kw, v in FALLBACK_RULES:
        if kw in name:
            return v, "营养表未收录，按同类估算"
    return None, None


def main():
    menu = json.loads((ASSETS / "menu-snapshot.json").read_text(encoding="utf-8"))
    nutrition = parse_nutrition(json.loads((ASSETS / "nutrition.json").read_text(encoding="utf-8"))["data"])

    items = []
    for code, m in menu["data"]["meals"].items():
        name = m["name"]
        kcal, note = kcal_for(name, nutrition)
        aliases = ALIASES.get(name, [])
        if not aliases:
            # 只对"套餐"后缀生成缩写别名；不动"三件套/四件套/汉堡/堡"——会与单品名冲突
            short = re.sub(r"(中|大)?套餐$", "", name)
            if 1 < len(short) < len(name):
                aliases = [short]
        items.append({"name": name, "code": code, "price": float(m["currentPrice"]),
                      "kcal": kcal, "kcal_note": note, "aliases": aliases})

    doc = {"_snapshot": {"date": menu["_snapshot"]["date"], "note": "菜单×营养合并索引；AI 出单冷启动只读本文件"},
           "items": items}
    out = ASSETS / "index.json"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    matched = sum(1 for i in items if i["kcal"] is not None)
    print(f"OK index.json: {len(items)} 品项，营养匹配 {matched}/{len(items)}，{out.stat().st_size} bytes")


if __name__ == "__main__":
    main()
