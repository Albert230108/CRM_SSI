# SwiftHK WhatsApp Service

Headless Node.js microservice that sends WhatsApp messages for SwiftHK through `whatsapp-web.js`.

## Install

1. Install dependencies:

   ```bash
   npm install
   ```

2. Copy `.env.example` to `.env` and set:
   - `API_KEY`
   - `PORT` if you do not want the default `3000`
   - `CRM_WHATSAPP_WEBHOOK_URL`
   - `CRM_WEBHOOK_SECRET` if your CRM expects a shared secret header

3. Make sure SwiftHK points at this service by setting the same key in:
   - `swifthk/.env` -> `WHATSAPP_API_KEY`
   - `swifthk/.env` -> `WHATSAPP_SERVICE_URL`

4. Start the service:

   ```bash
   npm start
   ```

## First Run QR

The first launch prints a QR code in the terminal or journal output. Scan it in WhatsApp:

1. Open WhatsApp on your phone.
2. Go to `Linked devices`.
3. Scan the QR code shown by the service.

The session is persisted by `LocalAuth`, so the QR scan is only needed once unless the session is removed.

## API

`POST /send`

Headers:

```http
X-API-Key: your-api-key
Content-Type: application/json
```

Body:

```json
{
  "to": "+31612345678",
  "message": "Hello"
}
```

Successful responses return:

```json
{ "ok": true }
```

## CRM forwarding

Incoming user messages are forwarded to the CRM webhook as a compact JSON payload with these fields:

- `direction`: `inbound`
- `from` and `sender`
- `sender_raw` and `sender_normalized`
- `message`, `body`, and `text`
- `timestamp`
- `whatsapp_message_id`
- `whatsapp_chat_id`
- `whatsapp_author`
- `whatsapp_type`
- `whatsapp_client_id`
- `provider`
- `external_account_id`
- `is_group`

Outbound replies sent by the local account are also forwarded with the same shape, plus:

- `direction`: `outbound`
- `to`
- `recipient`

Messages sent by the local account and status updates are ignored for inbound forwarding.

Historical backfill uses the same payload shape, supports both inbound and outbound messages, sorts messages chronologically before forwarding, and skips messages already seen in this process by `whatsapp_message_id`.

Backfill can be triggered in either of these ways:

- Set `WHATSAPP_HISTORY_BACKFILL_ENABLED=true` to run automatically after the client becomes ready.
- Call `POST /admin/backfill` with `X-API-Key` to run it manually.

## systemd

1. Copy `whatsapp-service.service` to `/etc/systemd/system/whatsapp-service.service`.
2. Edit `WorkingDirectory`, `EnvironmentFile`, and `User` so they match your server path and account.
3. Reload systemd:

   ```bash
   sudo systemctl daemon-reload
   ```

4. Enable and start the service:

   ```bash
   sudo systemctl enable --now whatsapp-service
   ```

5. Watch the logs, including the first-run QR output:

   ```bash
   journalctl -u whatsapp-service -f
   ```
