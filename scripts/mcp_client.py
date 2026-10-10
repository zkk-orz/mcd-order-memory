#!/usr/bin/env python3
"""麦当劳 MCP 零依赖客户端（L1 实时层；Streamable HTTP + Bearer Token）。

用法：
  python scripts/mcp_client.py list
  python scripts/mcp_client.py call query-nearby-stores '{"city":"北京市","keyword":"王府井"}'

环境变量：MCD_MCP_TOKEN（必需；缺失时给出中文指引后退出，绝不打印堆栈）。
只读查询工具可放心调用；写操作（create-order/cancel-order/mall-create-order/
draw-lottery/auto-bind-coupons/delivery-create-address）必须已经过确认门。
"""
import json
import os
import sys
import urllib.request

BASE_URL = "https://mcp.mcd.cn"

# 写操作工具：真实交易/资产变更，脚本层强制确认门（四道闸第 2 道的硬防线）。
# 调用必须附加 --i-confirm，且仅在已向用户预览并取得明确确认词之后。
WRITE_TOOLS = {
    "create-order", "cancel-order", "mall-create-order", "draw-lottery",
    "auto-bind-coupons", "delivery-create-address", "party-order-create",
}


class McpError(Exception):
    pass


def extract_payload(text):
    """content text 有三种形态：纯 JSON｜说明文本+内嵌业务 JSON（{"success","data"}）｜纯文本（如 CSV）。
    返回业务数据（dict/list/str）；业务层 success=false 时抛 McpError（含 code/message/traceId）。"""
    data = None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        dec = json.JSONDecoder()
        for i, ch in enumerate(text):
            if ch == "{":
                try:
                    obj, _ = dec.raw_decode(text, i)
                    if isinstance(obj, dict):
                        data = obj
                        break
                except json.JSONDecodeError:
                    continue
        if data is None:
            return text  # 纯文本（如营养表 CSV）
    if isinstance(data, dict) and "success" in data and "data" in data:
        if not data.get("success", True):
            raise McpError(f"[{data.get('code')}] {data.get('message')} (traceId:{data.get('traceId','')})")
        return data["data"]
    return data


def _post(payload, token):
    req = urllib.request.Request(
        BASE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "Authorization": f"Bearer {token}",
        },
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        raw = resp.read().decode("utf-8")
    # Streamable HTTP 可能返回 SSE（data: 行）或纯 JSON
    parsed = None
    for line in raw.splitlines():
        if line.startswith("data:"):
            try:
                parsed = json.loads(line[5:].strip())
            except json.JSONDecodeError:
                continue
    if parsed is None:
        parsed = json.loads(raw)
    if "error" in parsed:
        raise McpError(parsed["error"].get("message", str(parsed["error"])))
    return parsed.get("result", {})


def main():
    token = os.environ.get("MCD_MCP_TOKEN", "")
    if not token:
        print(json.dumps({"ok": False, "hint": "未设置环境变量 MCD_MCP_TOKEN。L0 快照功能无需 Token；"
                             "如需实时价格/下单等 L1 能力，请到 open.mcd.cn 申请后设置该环境变量。"}, ensure_ascii=False))
        sys.exit(1)
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "list":
            result = _post({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}, token)
            tools = [{"name": t["name"], "description": (t.get("description") or "").splitlines()[0]} for t in result.get("tools", [])]
            print(json.dumps({"ok": True, "count": len(tools), "tools": tools}, ensure_ascii=False, indent=1))
        elif cmd == "call":
            tool, raw_args = sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "{}"
            if tool in WRITE_TOOLS and "--i-confirm" not in sys.argv[4:]:
                print(json.dumps({"ok": False, "blocked": True, "hint": f"{tool} 是写操作（真实交易/资产变更）。"
                                     "四道闸：先向用户预览（清单+实付价）→取得明确确认词→才在本命令追加 --i-confirm 执行→回报结果。",
                                     }, ensure_ascii=False))
                sys.exit(3)
            result = _post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                            "params": {"name": tool, "arguments": json.loads(raw_args)}}, token)
            text = "".join(c.get("text", "") for c in result.get("content", []) if c.get("type") == "text")
            data = extract_payload(text)
            print(json.dumps({"ok": not result.get("isError", False), "tool": tool, "data": data}, ensure_ascii=False, indent=1))
        else:
            print(__doc__)
            sys.exit(2)
    except McpError as e:
        print(json.dumps({"ok": False, "error": str(e)}, ensure_ascii=False)); sys.exit(1)
    except urllib.error.HTTPError as e:
        print(json.dumps({"ok": False, "error": f"HTTP {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}"}, ensure_ascii=False)); sys.exit(1)


if __name__ == "__main__":
    main()
