---
name: zoho-mail
description: >-
  Work with Zoho Mail through the connected zoho-mail MCP server. Use when the user
  asks to read, search, summarize, triage, send, reply, archive, label, flag, file,
  set a vacation reply, or run any recurring mailbox workflow in Zoho Mail.
---

# Zoho Mail

The `zoho-mail` MCP server exposes the Zoho Mail API as tools. Tool names match Zoho's
own first-party MCP naming, so the same recipe works for either server.

## Before the first mail action

1. Call `getMailAccounts` once per run and keep the `accountId` and the sending address.
   Every other tool needs the account ID.
2. If the server returns an authentication or permission error, stop and tell the user to
   connect or reconnect `zoho-mail` under **Integrations** — never guess an account ID.

## Reading and searching

- `listEmails` for a folder view (defaults to the Inbox). Ask for a `limit` that fits the
  request; 20 is a good first page.
- `SearchEmails` when the user names a sender, subject word, date range or body phrase.
  Prefer search over paging through `listEmails`.
- `listEmails` and `SearchEmails` return summaries. Call `getMessageContent` for the body
  of the specific messages you will actually quote or act on.
- `getMessageAttachmentInfo` before claiming a message has or lacks attachments.

Report mail as sender, date, subject, and the one-line reason it matters. Quote only the
lines the user asked about.

## Sending

Sending mail is a side effect. Before calling `sendEmail` or `sendReplyMail`:

1. Show the exact recipients, subject, and body you are about to send.
2. Get the user's approval in this conversation. For a draft they asked you to prepare,
   stop at the draft unless they say to send it.
3. `sendReplyMail` needs the original `messageId`; get it from a search or list call in
   the same run rather than from memory.

## Filing and organizing

- `getAllFolders` before moving anything, so you use real folder IDs. `createFolder` only
  when no suitable folder exists.
- `moveMessages` to file, `archiveMessage` to get something out of the Inbox without
  deleting it, `unarchiveMessage` to bring it back.
- `applyLabelToMessages` and `removeLabelFromMessage` for labels; `flagMessages` for
  important / follow-up / info.
- `deleteEmail` is destructive. Delete only the exact message IDs the user named, one
  confirmed batch at a time.

## Settings that change live behaviour

`addVacationReply`, `updateVacationReply`, `addMailForward`, `enableMailForward` and
`deleteEmail` change what happens to future incoming mail. State plainly what will change,
who will be affected, and how to undo it, then wait for approval.

## Recurring work

For "every morning" or "watch my inbox" requests, use a routine: search or list with the
same tools, summarize, and only send or file when the standing instruction already grants
it. A standing instruction to summarize is not permission to send.
