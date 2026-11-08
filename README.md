# Zoho Mail plugin for Rakazo

A [Rakazo plugin](https://rakazo.com/docs/build-a-plugin/) that gives any bot in your space a
working Zoho Mail mailbox: search and read mail, send and reply, file into folders, label, flag,
archive, and set an out-of-office reply.

Three parts:

| Path | What it does |
| --- | --- |
| `plugin.json` + `mcp.json` | The plugin Rakazo installs. One MCP server named `zoho-mail`. |
| `skills/zoho-mail/SKILL.md` | Teaches bots when to call each tool and when to stop and ask. |
| `server/zoho_mail_mcp.py` | The hosted MCP server: a streamable-HTTP layer over the Zoho Mail REST API. |

Rakazo reads only the plugin files; it never runs code from this repository. So the server has to be
deployed somewhere public before the plugin does anything.

## Why a server at all

Zoho's own console at [mcp.zoho.com](https://mcp.zoho.com) mints a *unique* MCP URL per account and
tells you to treat that URL like a password. A public plugin repository cannot contain it, and Rakazo
rejects `${VAR}` placeholders in `mcp.json`. This plugin instead points at one stable endpoint that
you deploy once; the mailbox secret stays in your server's environment, or in Rakazo's encrypted
credential store — never in the repo.

Just for yourself, and don't want to run anything? Skip the plugin: **Integrations → + → MCP server**
in Rakazo, paste your Zoho MCP URL, **Verify and add**.

## Layout

```text
plugin.json                     manifest (Agent Plugins 1.0.0)
mcp.json                        the zoho-mail streamable-http server
skills/zoho-mail/SKILL.md       how bots should use the tools
server/zoho_mail_mcp.py         the MCP server (Python, MCP SDK 2.x)
server/requirements.txt         mcp>=2,<3, httpx
server/.env.example             environment template
server/check_server.py          offline check: tools, schemas, auth guard
server/smoke_connect.py         connects to a running server over streamable HTTP
check_manifests.py              validates the two manifests before you publish
Dockerfile                      container image
```

## 1. Deploy the server

Create a Zoho OAuth client at [Zoho Console](https://console.zoho.com) (Global Client or Self Client)
with these scopes, then generate a refresh token:

```text
ZohoMail.accounts.READ
ZohoMail.messages.READ
ZohoMail.messages.CREATE
ZohoMail.folders.READ
ZohoMail.folders.CREATE
```

Run it anywhere that gives you a public HTTPS URL — Fly.io, Railway, Render, Cloud Run, or your own
box behind Caddy/nginx:

```bash
cp server/.env.example server/.env     # client id, secret, refresh token, data centre
docker build -t zoho-mail-mcp .
docker run --env-file server/.env -p 8080:8080 zoho-mail-mcp
# endpoint: https://your-host/mcp
```

Or without Docker: `uv run --with mcp --with httpx python server/zoho_mail_mcp.py`
(`MCP_HOST` / `MCP_PORT` control the bind address; default `0.0.0.0:8080`).

The server gets its Zoho token one of two ways, checked in that order:

1. **The caller's `Authorization` header.** Rakazo sends it when you put a Zoho access token under
   **Integrations → Manage MCP servers → zoho-mail → Advanced → Access token**. No secret lives on
   your server, but Zoho access tokens last about an hour.
2. **`ZOHOMAIL_REFRESH_TOKEN`** plus client id and secret, refreshed automatically and cached in
   memory. Use this for a shared or long-running deployment.

Serve one mailbox per deployment, or one per team, and keep the endpoint private: anyone who can
reach it with a valid token can read that mailbox. Require the header, or restrict by IP / mTLS.

## 2. Point the plugin at your deployment

In `mcp.json`, replace the placeholder with the URL from step 1:

```json
{
  "mcpServers": {
    "zoho-mail": {
      "type": "streamable-http",
      "url": "https://your-host/mcp",
      "headers": { "X-Zoho-Mail-Tools": "user" }
    }
  }
}
```

`mcp.json` accepts only `type`, `url` and `headers`, and `headers` is for non-secret configuration.
`X-Zoho-Mail-Tools` is metadata, not auth. Keep credentials out of both files and out of the URL.

## 3. Check it before publishing

```bash
uv run --with jsonschema --with httpx python check_manifests.py
uv run --with mcp --with httpx python server/check_server.py
```

Both must pass. Then run the server locally and connect to it as a client would:

```bash
MCP_PORT=8099 python server/zoho_mail_mcp.py &
uv run --with mcp --with httpx python server/smoke_connect.py http://127.0.0.1:8099/mcp
```

## 4. Install in Rakazo

1. Push this folder to a **public** GitHub repository (private repos and local folders are not
   installable sources).
2. Rakazo: **Integrations → + → From GitHub**, paste the repo URL (or the folder URL if the plugin
   sits in a subdirectory), choose **Preview**.
3. Confirm the preview lists the `zoho-mail` server and the `zoho-mail` skill with nothing skipped.
   Choose **Connect** for the server, then **Add skills**.
4. If the server needs a token, **Manage MCP servers → zoho-mail → Advanced → Access token**, then
   **Test connection**.
5. With a bot selected, **Use in this bot**, and ask it something real:
   *"What came in from billing@vendor.com this week?"*

A valid config does not prove the tools work. Do one read and one draft before you trust it.

## 5. Submit to the marketplace (optional)

Submit at [rakazo.com/plugins/submit](https://rakazo.com/plugins/submit/) with the repo URL, an HTTPS
logo URL, and testing instructions that exercise the tools **without** real credentials. Review
checks the live endpoint, so step 2 has to point at a running server. Installs stay pinned to the
commit that was previewed; push an update, then remove and reinstall to test it.

## Tools this server exposes

Names match Zoho's own MCP tool names, so the companion skill works against either server.

- Discovery: `getMailAccounts`, `getAccountDetails`, `getAllFolders`, `getAllLabels`
- Reading: `listEmails`, `SearchEmails`, `getMessageContent`, `getMessageAttachmentInfo`
- Sending: `sendEmail`, `sendReplyMail`, `saveDraft`
- Organizing: `moveMessages`, `archiveMessage`, `unarchiveMessage`, `markEmails`, `flagMessages`,
  `applyLabelToMessages`, `removeLabelFromMessage`, `createFolder`, `deleteEmail`
- Settings: `addVacationReply`, `deleteVacationReply`

Read-only tools are annotated `readOnlyHint`, and `deleteEmail` is annotated `destructiveHint`, so
clients can show the difference before a call runs.

## Verified on 2026-11-08

- `check_manifests.py`: `plugin.json` and `mcp.json` validate against the published Agent Plugins
  1.0.0 schemas; name, server keys, HTTPS URL and header rules pass. (Rakazo's docs show a 1.1.0
  `$schema`; that URL currently 404s at agent-plugins.org, and Rakazo reads 1.0.0 manifests, so this
  repo uses the fetchable 1.0.0 identifier in both files.)
- `server/check_server.py`: 22 tools register, no `ctx` parameter leaks into any input schema, every
  tool has a description, and with no credentials configured `getMailAccounts` fails with
  "No Zoho access token" instead of touching a mailbox.
- `server/smoke_connect.py` against a live local server: streamable-HTTP handshake, `initialize`
  reports server name `zoho-mail`, `tools/list` returns all 22 tools, `tools/call` returns an
  MCP-level error rather than crashing the server.
- Token refresh wiring reached `https://accounts.zoho.com/oauth/v2/token` with the documented
  `grant_type=refresh_token` query. No real Zoho mailbox was contacted — that needs your own
  credentials, which is why the last check on the list is yours to run.

## Known rough edges

- Zoho documents both `/api/v1/...` and `/api/...` shapes, and lists the folder listing as both
  `/messages` and `/messages/view`. The server uses `/api/v1` and retries `/view` on a 404. Set
  `ZOHOMAIL_API_BASE` if your data centre differs.
- `getMessageContent` wants a `folder_id` for some accounts; without one the server falls back to the
  message metadata endpoint, which can omit the body.
- Zoho's search `criteria` syntax is passed through untouched; a rejected query comes back as the
  API's own error text.
- Admin APIs (users, domains, spam policies) are not wrapped. Add them the same way: one
  `@mcp.tool` function per Zoho endpoint.

MIT licensed. Not affiliated with Zoho Corp.
