"""临时回归脚本（A 段补测） - 测完即删。"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


BASE = "http://127.0.0.1:8000/mcp"
TOKEN = "pvt_pYAes1i7jMcbKwRvCkF7IItFw_ZF63aMSql3kBEhimY"
INVALID = "pvt_definitelyNotARealToken_zzz"


def _parse(res) -> Any:
    c = res.content
    if not c:
        return {"_empty": True}
    return json.loads(getattr(c[0], "text", ""))


async def session(token: str):
    client = httpx.AsyncClient(
        headers={"Authorization": f"Bearer {token}"},
        timeout=httpx.Timeout(10.0, read=30.0),
        follow_redirects=True,
        trust_env=False,
    )
    return client


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    arg = sys.argv[2] if len(sys.argv) > 2 else None

    if cmd == "401":
        c = await session(INVALID)
        async with c:
            try:
                async with streamable_http_client(BASE, http_client=c) as (r, w, _):
                    async with ClientSession(r, w) as s:
                        await s.initialize()
                print("UNEXPECTED: connected with invalid token")
            except Exception as e:
                print("OK 401 path:", type(e).__name__, str(e)[:300])
        return

    c = await session(TOKEN)
    async with c:
        async with streamable_http_client(BASE, http_client=c) as (r, w, _):
            async with ClientSession(r, w) as s:
                await s.initialize()

                if cmd == "list":
                    res = await s.call_tool("list_matters", {})
                    out = _parse(res)
                    items = out.get("items") or out.get("matters") or []
                    print(f"matter count: {len(items)}")
                    for m in items:
                        print(f"  {m.get('matter_id')!r}  status={m.get('status')!r}  title={m.get('title')!r}")
                    return

                if cmd == "get":
                    res = await s.call_tool("get_matter", {"matter_id": arg})
                    print(json.dumps(_parse(res), ensure_ascii=False, indent=2)[:4000])
                    return

                if cmd == "read":
                    paths = json.loads(arg)
                    res = await s.call_tool("read_files", {"matter_id": sys.argv[3], "paths": paths})
                    out = _parse(res)
                    if isinstance(out, dict) and "errors" in out:
                        print("ERRORS:", json.dumps(out, ensure_ascii=False))
                        return
                    files = out.get("files") if isinstance(out, dict) else out
                    if not isinstance(files, list):
                        print(json.dumps(out, ensure_ascii=False)[:1000])
                        return
                    for f in files:
                        body = f.get("body") or ""
                        print(f"  path={f.get('path')!r} truncated={f.get('truncated')} body_chars={len(body)}")
                    return

                if cmd == "create":
                    payload = json.loads(arg)
                    res = await s.call_tool("create_file", payload)
                    print(json.dumps(_parse(res), ensure_ascii=False, indent=2)[:3000])
                    return

                if cmd == "resolve":
                    res = await s.call_tool("resolve_context", {"url": arg})
                    print(json.dumps(_parse(res), ensure_ascii=False, indent=2)[:3000])
                    return

                print("unknown cmd:", cmd)


if __name__ == "__main__":
    asyncio.run(main())
