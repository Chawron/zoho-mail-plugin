"""Connect to a running zoho-mail MCP server over streamable HTTP and exercise it.

    python server/smoke_connect.py [url]      # default http://127.0.0.1:8099/mcp
"""

import asyncio
import sys

from mcp.client import Client


async def run(url: str) -> None:
    async with Client(url) as client:
        info = client.server_info
        print(f"connected to {info.name!r} at {url}")
        tools = (await client.list_tools()).tools
        print(f"tools: {len(tools)}")
        print(", ".join(t.name for t in tools[:6]), "...")

        result = await client.call_tool("getMailAccounts", {})
        text = "".join(c.text for c in result.content if hasattr(c, "text"))
        print(f"call getMailAccounts -> isError={result.is_error}")
        print("message:", text[:200])


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099/mcp"))
