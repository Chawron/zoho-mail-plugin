"""Zoho Mail MCP server.

Exposes the Zoho Mail REST API as MCP tools over streamable HTTP, so a Rakazo plugin can point at
one public HTTPS endpoint instead of a per-account secret URL.

Written for the MCP Python SDK 2.x (``mcp>=2,<3``).

Authentication, in order of precedence:
  1. An ``Authorization`` header on the MCP request ("Bearer <token>" or
     "Zoho-oauthtoken <token>") is forwarded to Zoho as the account's token.
  2. Otherwise the server refreshes a stored Zoho OAuth refresh token built from
     ZOHOMAIL_CLIENT_ID / ZOHOMAIL_CLIENT_SECRET / ZOHOMAIL_REFRESH_TOKEN.

Env vars:
  ZOHOMAIL_API_BASE       default https://mail.zoho.com  (US DC; other data centres use
                          mail.zoho.eu, mail.zoho.in, mail.zoho.com.au, mail.zoho.jp,
                          mail.zohocloud.ca, mail.zoho.com.cn, mail.zoho.ae, mail.zoho.sa)
  ZOHOMAIL_ACCOUNTS_BASE  default https://accounts.zoho.com (same TLD as the mail domain)
  ZOHOMAIL_CLIENT_ID / ZOHOMAIL_CLIENT_SECRET / ZOHOMAIL_REFRESH_TOKEN
  ZOHOMAIL_DEFAULT_ACCOUNT_ID  optional, skips the account lookup
  MCP_HOST / MCP_PORT          bind address for the streamable HTTP endpoint
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Mapping

import httpx
from mcp.server.mcpserver import Context, MCPServer
from mcp.types import ToolAnnotations

API_BASE = os.environ.get("ZOHOMAIL_API_BASE", "https://mail.zoho.com").rstrip("/")
ACCOUNTS_BASE = os.environ.get("ZOHOMAIL_ACCOUNTS_BASE", "https://accounts.zoho.com").rstrip("/")
CLIENT_ID = os.environ.get("ZOHOMAIL_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("ZOHOMAIL_CLIENT_SECRET", "")
REFRESH_TOKEN = os.environ.get("ZOHOMAIL_REFRESH_TOKEN", "")
DEFAULT_ACCOUNT_ID = os.environ.get("ZOHOMAIL_DEFAULT_ACCOUNT_ID", "")

_cached_token: tuple[str, float] | None = None  # (access_token, expires_at)

INSTRUCTIONS = (
    "Zoho Mail tools. Call getMailAccounts once per run and reuse the accountId. "
    "Sending, deleting, forwarding and vacation replies change a live mailbox: show the user "
    "what will happen and get their approval before calling those tools."
)

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=True)
WRITE = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True)
DESTRUCTIVE = ToolAnnotations(readOnlyHint=False, destructiveHint=True, openWorldHint=True)

mcp = MCPServer("zoho-mail", instructions=INSTRUCTIONS)


# --------------------------------------------------------------------------- auth


def _forwarded_token(ctx: Context | None) -> str | None:
    """Use the caller's Authorization header when the client supplied one."""
    if ctx is None:
        return None
    try:  # ctx.headers raises when there is no HTTP request behind the call
        headers: Mapping[str, str] | None = ctx.headers
    except Exception:
        return None
    if not headers:
        return None
    header = headers.get("authorization") or headers.get("Authorization") or ""
    if not header:
        return None
    _scheme, _, value = header.partition(" ")
    return value.strip() or None


def _refreshed_token() -> str:
    """Exchange the stored refresh token for a live Zoho access token."""
    global _cached_token
    if not (CLIENT_ID and CLIENT_SECRET and REFRESH_TOKEN):
        raise RuntimeError(
            "No Zoho access token. Either put a Zoho access token under Rakazo > Integrations > "
            "Manage MCP servers > zoho-mail > Advanced > Access token, or set ZOHOMAIL_CLIENT_ID, "
            "ZOHOMAIL_CLIENT_SECRET and ZOHOMAIL_REFRESH_TOKEN in the server environment."
        )
    if _cached_token and _cached_token[1] > time.time() + 60:
        return _cached_token[0]
    response = httpx.post(
        f"{ACCOUNTS_BASE}/oauth/v2/token",
        params={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": REFRESH_TOKEN,
        },
        timeout=30.0,
    )
    response.raise_for_status()
    payload = response.json()
    token = payload.get("access_token")
    if not token:
        raise RuntimeError(f"Zoho returned no access token: {payload.get('error', payload)}")
    _cached_token = (str(token), time.time() + float(payload.get("expires_in", 3600)))
    return str(token)


def _token(ctx: Context | None) -> str:
    return _forwarded_token(ctx) or _refreshed_token()


# -------------------------------------------------------------------------- http


def _request(ctx: Context | None, method: str, path: str, *, params: dict, data: dict | None):
    return httpx.request(
        method,
        f"{API_BASE}/api/v1{path}",
        params=params,
        data=data,
        headers={"Authorization": f"Zoho-oauthtoken {_token(ctx)}"},
        timeout=60.0,
    )


def _call(
    ctx: Context | None,
    method: str,
    path: str,
    *,
    params: dict[str, Any] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = {k: v for k, v in (params or {}).items() if v not in (None, "")}
    body = {k: v for k, v in (data or {}).items() if v not in (None, "")}
    response = _request(ctx, method, path, params=query, data=body or None)
    if response.status_code == 404 and method == "GET" and path.endswith("/messages"):
        # Zoho documents the folder listing as both /messages and /messages/view.
        response = _request(ctx, method, f"{path}/view", params=query, data=None)
    if response.status_code >= 400:
        raise RuntimeError(
            f"Zoho Mail {method} {path} -> {response.status_code}: {response.text[:600]}"
        )
    try:
        return response.json()
    except json.JSONDecodeError:
        return {"raw": response.text}


def _account_id(account_id: str) -> str:
    account = str(account_id or DEFAULT_ACCOUNT_ID or "")
    if not account:
        raise RuntimeError("accountId is empty. Call getMailAccounts first and pass its accountId.")
    return account


def _summary(payload: dict[str, Any]) -> str:
    """Compact JSON: the model sees the mail, not API noise."""
    return json.dumps(payload, ensure_ascii=False)[:12000]


# --------------------------------------------------------------------- discovery


@mcp.tool(name="getMailAccounts", title="List Zoho Mail accounts", annotations=READ)
def get_mail_accounts(ctx: Context) -> str:
    """Account IDs and addresses for the signed-in user. Call before any other tool."""
    return _summary(_call(ctx, "GET", "/accounts"))


@mcp.tool(name="getAccountDetails", title="Get one account's details", annotations=READ)
def get_account_details(account_id: str, ctx: Context) -> str:
    """Whether an account is active, plus its display name and address."""
    return _summary(_call(ctx, "GET", f"/accounts/{_account_id(account_id)}"))


@mcp.tool(name="getAllFolders", title="List mailbox folders", annotations=READ)
def get_all_folders(account_id: str, ctx: Context) -> str:
    """Folder IDs, needed by move, unarchive, delete and content calls."""
    return _summary(_call(ctx, "GET", f"/accounts/{_account_id(account_id)}/folders"))


@mcp.tool(name="getAllLabels", title="List mailbox labels", annotations=READ)
def get_all_labels(account_id: str, ctx: Context) -> str:
    """Label names and IDs available in the account."""
    return _summary(_call(ctx, "GET", f"/accounts/{_account_id(account_id)}/labels"))


# ----------------------------------------------------------------------- reading


@mcp.tool(name="listEmails", title="List emails in a folder", annotations=READ)
def list_emails(
    account_id: str,
    ctx: Context,
    folder_id: str = "",
    limit: int = 20,
    start_index: int = 0,
    order_by: str = "receivedTime",
) -> str:
    """Summaries (sender, subject, date, messageId, threadId), newest first.

    Blank folder_id means the Inbox. Page with start_index.
    """
    return _summary(
        _call(
            ctx,
            "GET",
            f"/accounts/{_account_id(account_id)}/messages",
            params={
                "folderId": folder_id,
                "limit": max(1, min(int(limit), 100)),
                "startIndex": max(0, int(start_index)),
                "orderBy": order_by,
            },
        )
    )


@mcp.tool(name="SearchEmails", title="Search emails", annotations=READ)
def search_emails(
    account_id: str,
    criteria: str,
    ctx: Context,
    folder_id: str = "",
    limit: int = 20,
) -> str:
    """Zoho search syntax, for example 'from:boss@corp.com subject:invoice after:2026-11-01'."""
    return _summary(
        _call(
            ctx,
            "GET",
            f"/accounts/{_account_id(account_id)}/messages/search",
            params={
                "criteria": criteria,
                "folderId": folder_id,
                "limit": max(1, min(int(limit), 100)),
            },
        )
    )


@mcp.tool(name="getMessageContent", title="Read one email", annotations=READ)
def get_message_content(
    message_id: str, ctx: Context, account_id: str = "", folder_id: str = ""
) -> str:
    """Body and headers of one message.

    Pass folder_id from listEmails or getAllFolders when you have it; without it the server
    falls back to the message metadata endpoint, which may omit the body.
    """
    account = _account_id(account_id)
    path = (
        f"/accounts/{account}/folders/{folder_id}/messages/{message_id}/content"
        if folder_id
        else f"/accounts/{account}/messages/{message_id}"
    )
    return _summary(_call(ctx, "GET", path))


@mcp.tool(name="getMessageAttachmentInfo", title="Inspect attachments", annotations=READ)
def get_message_attachment_info(
    message_id: str, folder_id: str, ctx: Context, account_id: str = ""
) -> str:
    """Attachment names, types and sizes (inline or not) for one message."""
    account = _account_id(account_id)
    return _summary(
        _call(
            ctx,
            "GET",
            f"/accounts/{account}/folders/{folder_id}/messages/{message_id}/attachmentinfo",
        )
    )


# ----------------------------------------------------------------------- sending


@mcp.tool(name="sendEmail", title="Send an email", annotations=WRITE)
def send_email(
    account_id: str,
    from_address: str,
    to_address: str,
    subject: str,
    content: str,
    ctx: Context,
    cc_address: str = "",
    bcc_address: str = "",
    mail_format: str = "plain",
) -> str:
    """Sends immediately. Only call after the user has approved the exact recipients, subject
    and body in this conversation. Separate multiple addresses with commas.

    mail_format is plain or html.
    """
    account = _account_id(account_id)
    return _summary(
        _call(
            ctx,
            "POST",
            f"/accounts/{account}/messages",
            data={
                "fromAddress": from_address,
                "toAddress": to_address,
                "ccAddress": cc_address,
                "bccAddress": bcc_address,
                "subject": subject,
                "content": content,
                "mailFormat": mail_format,
                "action": "send",
            },
        )
    )


@mcp.tool(name="sendReplyMail", title="Reply to an email", annotations=WRITE)
def send_reply_mail(
    account_id: str,
    message_id: str,
    from_address: str,
    content: str,
    ctx: Context,
    reply_all: bool = False,
) -> str:
    """Replies into an existing thread. The messageId must come from a tool call in this run."""
    account = _account_id(account_id)
    return _summary(
        _call(
            ctx,
            "POST",
            f"/accounts/{account}/messages/{message_id}",
            data={
                "fromAddress": from_address,
                "content": content,
                "action": "replyall" if reply_all else "reply",
            },
        )
    )


@mcp.tool(name="saveDraft", title="Save a draft", annotations=WRITE)
def save_draft(
    account_id: str,
    from_address: str,
    to_address: str,
    subject: str,
    content: str,
    ctx: Context,
    mail_format: str = "plain",
) -> str:
    """Stores a message in Drafts without sending. Prefer this when the user is unsure."""
    account = _account_id(account_id)
    return _summary(
        _call(
            ctx,
            "POST",
            f"/accounts/{account}/messages",
            data={
                "fromAddress": from_address,
                "toAddress": to_address,
                "subject": subject,
                "content": content,
                "mailFormat": mail_format,
                "action": "save",
            },
        )
    )


# --------------------------------------------------------------------- organizing


def _update_message(ctx: Context, account_id: str, data: dict[str, Any]) -> str:
    return _summary(_call(ctx, "PUT", f"/accounts/{_account_id(account_id)}/updatemessage", data=data))


@mcp.tool(name="moveMessages", title="Move emails to a folder", annotations=WRITE)
def move_messages(account_id: str, message_ids: str, folder_id: str, ctx: Context) -> str:
    """message_ids is comma separated. folder_id comes from getAllFolders."""
    return _update_message(
        ctx, account_id, {"messageIds": message_ids, "action": "move", "folderId": folder_id}
    )


@mcp.tool(name="archiveMessage", title="Archive emails", annotations=WRITE)
def archive_message(account_id: str, message_ids: str, ctx: Context) -> str:
    """Removes from the Inbox without deleting. message_ids is comma separated."""
    return _update_message(ctx, account_id, {"messageIds": message_ids, "action": "archive"})


@mcp.tool(name="unarchiveMessage", title="Unarchive emails", annotations=WRITE)
def unarchive_message(account_id: str, message_ids: str, folder_id: str, ctx: Context) -> str:
    """Returns archived mail to a folder."""
    return _update_message(
        ctx, account_id, {"messageIds": message_ids, "action": "unarchive", "folderId": folder_id}
    )


@mcp.tool(name="markEmails", title="Mark emails read or unread", annotations=WRITE)
def mark_emails(account_id: str, message_ids: str, read: bool, ctx: Context) -> str:
    """read true marks as read, false marks as unread."""
    return _update_message(
        ctx, account_id, {"messageIds": message_ids, "action": "markread" if read else "markunread"}
    )


@mcp.tool(name="flagMessages", title="Flag emails", annotations=WRITE)
def flag_messages(account_id: str, message_ids: str, ctx: Context, flag: str = "important") -> str:
    """flag is one of: important, follow-up, info, forward."""
    return _update_message(ctx, account_id, {"messageIds": message_ids, "action": "flags", "flag": flag})


@mcp.tool(name="applyLabelToMessages", title="Apply a label", annotations=WRITE)
def apply_label_to_messages(account_id: str, message_ids: str, label_name: str, ctx: Context) -> str:
    """label_name must already exist; check it with getAllLabels."""
    return _update_message(
        ctx, account_id, {"messageIds": message_ids, "action": "addlabel", "labelNames": label_name}
    )


@mcp.tool(name="removeLabelFromMessage", title="Remove a label", annotations=WRITE)
def remove_label_from_message(account_id: str, message_ids: str, label_name: str, ctx: Context) -> str:
    """Removes one label from the given messages."""
    return _update_message(
        ctx, account_id, {"messageIds": message_ids, "action": "removelabel", "labelNames": label_name}
    )


@mcp.tool(name="createFolder", title="Create a folder", annotations=WRITE)
def create_folder(
    account_id: str, folder_name: str, ctx: Context, parent_folder_id: str = ""
) -> str:
    """New mailbox folder. Blank parent_folder_id creates it at the top level."""
    return _summary(
        _call(
            ctx,
            "POST",
            f"/accounts/{_account_id(account_id)}/folders",
            data={"folderName": folder_name, "parentFolderId": parent_folder_id},
        )
    )


@mcp.tool(name="deleteEmail", title="Delete emails", annotations=DESTRUCTIVE)
def delete_email(account_id: str, folder_id: str, message_ids: str, ctx: Context) -> str:
    """Destructive. Deletes mail, only for the exact message IDs the user confirmed."""
    account = _account_id(account_id)
    return _summary(
        _call(ctx, "DELETE", f"/accounts/{account}/folders/{folder_id}/messages/{message_ids}")
    )


# ----------------------------------------------------------------------- settings


@mcp.tool(name="addVacationReply", title="Turn on an out-of-office reply", annotations=WRITE)
def add_vacation_reply(
    account_id: str, message: str, ctx: Context, from_date: str = "", to_date: str = "", subject: str = ""
) -> str:
    """Auto-replies to incoming mail. Changes behaviour for everyone who mails this address."""
    return _summary(
        _call(
            ctx,
            "POST",
            f"/accounts/{_account_id(account_id)}/vacation",
            data={
                "message": message,
                "fromDate": from_date,
                "toDate": to_date,
                "subject": subject,
                "vacationStatus": True,
            },
        )
    )


@mcp.tool(name="deleteVacationReply", title="Turn off an out-of-office reply", annotations=WRITE)
def delete_vacation_reply(account_id: str, ctx: Context) -> str:
    """Stops the vacation reply and restores normal delivery."""
    return _summary(_call(ctx, "DELETE", f"/accounts/{_account_id(account_id)}/vacation"))


def main() -> None:
    """Serve /mcp over streamable HTTP on MCP_HOST:MCP_PORT (default 0.0.0.0:8080)."""
    mcp.run(
        transport="streamable-http",
        host=os.environ.get("MCP_HOST", "0.0.0.0"),
        port=int(os.environ.get("MCP_PORT", "8080")),
        streamable_http_path="/mcp",
    )


if __name__ == "__main__":
    main()
