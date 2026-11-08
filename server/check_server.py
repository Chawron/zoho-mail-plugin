"""Offline check of the Zoho Mail MCP server: imports, tool registration, schemas, auth guard.

Run with the dependencies installed:
    uv run --with mcp --with httpx python server/check_server.py
"""

import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
for var in ("ZOHOMAIL_REFRESH_TOKEN", "ZOHOMAIL_CLIENT_ID", "ZOHOMAIL_CLIENT_SECRET"):
    os.environ.pop(var, None)

import zoho_mail_mcp as z  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402


def _messages(exc: BaseException) -> str:
    """The SDK wraps tool failures, so collect the whole cause chain."""
    parts = []
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        parts.append(str(exc))
        exc = exc.__cause__ or exc.__context__
    return " | ".join(parts)


def main() -> None:
    assert isinstance(z.mcp, MCPServer), "mcp is not an MCPServer instance"

    tools = asyncio.run(z.mcp.list_tools())
    print(f"registered tools: {len(tools)}")
    print(", ".join(t.name for t in tools))

    required = {
        "getMailAccounts",
        "listEmails",
        "SearchEmails",
        "getMessageContent",
        "sendEmail",
        "sendReplyMail",
        "deleteEmail",
        "addVacationReply",
    }
    missing = required - {t.name for t in tools}
    assert not missing, f"missing tools: {missing}"

    by_name = {t.name: t for t in tools}
    for tool in tools:
        props = tool.input_schema.get("properties", {})
        assert "ctx" not in props, f"{tool.name} leaks ctx into its schema"
        assert tool.description, f"{tool.name} has no description"
        assert json.dumps(tool.input_schema), f"{tool.name} has an unserialisable schema"

    # Side-effecting tools must warn in their description and be annotated.
    assert "approved" in by_name["sendEmail"].description.lower()
    assert "user" in by_name["deleteEmail"].description.lower()
    assert by_name["getMailAccounts"].annotations.read_only_hint is True
    assert by_name["deleteEmail"].annotations.destructive_hint is True

    # accountId is mandatory for most tools; the guard must be explicit, not a weird URL.
    try:
        z._account_id("")
    except RuntimeError as exc:
        assert "getMailAccounts" in str(exc)
    else:
        raise AssertionError("expected an accountId error")

    # Without credentials a call must fail loudly, not silently read someone else's mail.
    try:
        asyncio.run(z.mcp.call_tool("getMailAccounts", {}))
    except Exception as exc:  # expected
        assert "No Zoho access token" in _messages(exc), f"unexpected error: {exc}"
        print("auth guard raises when no token is configured: ok")
    else:
        raise AssertionError("expected an auth error")

    print("all checks passed")


if __name__ == "__main__":
    main()
