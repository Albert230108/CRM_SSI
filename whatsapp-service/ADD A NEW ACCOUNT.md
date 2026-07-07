Yes — to **add** another WhatsApp account, keep the current `crm-whatsapp.service` as-is and create a **second service instance** with its own port, `WHATSAPP_CLIENT_ID`, and stored auth session. `whatsapp-web.js` supports multiple sessions by separating them with `clientId`, which is the right way to run more than one linked account on the same machine. [wwebjs](https://wwebjs.dev/guide/creating-your-bot/authentication.html)

## What to create

Make a second copy of the CRM service config, for example:

- service name: `crm-whatsapp-2.service`
- port: `3002`
- `WHATSAPP_CLIENT_ID=crm-whatsapp-2`

Do **not** reuse the first service’s port or client ID, or the two instances can collide. Separate `clientId` values are specifically how `LocalAuth` distinguishes multiple sessions. [stackoverflow](https://stackoverflow.com/questions/75067529/whatsapp-web-js-multiple-sessions)

## Fast setup

### 1. Create a second env file
```bash
cd /home/ssi-edi-server/CRM-SSI/CRM_SSI/whatsapp-service
cp .env .env.crm2
nano .env.crm2
```

Change at least:

```env
PORT=3002
WHATSAPP_CLIENT_ID=crm-whatsapp-2
```

Keep your CRM webhook settings as needed for that account. Different instances should not share the same bind port, and different sessions should not share the same `clientId`. [docs.wwebjs](https://docs.wwebjs.dev/LocalAuth.html)

### 2. Create a second systemd service
```bash
sudo nano /etc/systemd/system/crm-whatsapp-2.service
```

Use:

```ini
[Unit]
Description=CRM WhatsApp service 2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ssi-edi-server/CRM-SSI/CRM_SSI/whatsapp-service
EnvironmentFile=/home/ssi-edi-server/CRM-SSI/CRM_SSI/whatsapp-service/.env.crm2
Environment=NODE_ENV=production
ExecStart=/usr/bin/node src/server.js
Restart=always
RestartSec=5
User=ssi-edi-server
Group=ssi-edi-server

[Install]
WantedBy=multi-user.target
```

A separate unit with a separate environment file is the cleanest way to run a second independent instance. [oneuptime](https://oneuptime.com/blog/post/2026-03-02-how-to-configure-systemd-service-environment-files-on-ubuntu/view)

### 3. Start it
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now crm-whatsapp-2.service
sudo journalctl -u crm-whatsapp-2.service -f
```

On first start, it should prompt for a QR login flow for the new account. Since the second instance uses a different `WHATSAPP_CLIENT_ID`, `LocalAuth` should keep its session separate from the first one. [wwebjs](https://wwebjs.dev/guide/creating-your-bot/authentication.html)

## Important note

This assumes your app’s `LocalAuth` setup actually uses `whatsappClientId` as the `clientId`. If it does, each instance gets its own stored WhatsApp session automatically; if it does not, you should patch that before relying on multi-account operation. Multiple-session support in `whatsapp-web.js` depends on distinct session identifiers. [docs.wwebjs](https://docs.wwebjs.dev/LocalAuth.html)

## Recommended values

For a safe second instance, use something like:

```env
PORT=3002
WHATSAPP_CLIENT_ID=crm-whatsapp-2
```

Keep the first instance on:
```env
PORT=3001
WHATSAPP_CLIENT_ID=edi-crm-whatsapp
```

That gives each service its own listener and its own WhatsApp session identity. [stackoverflow](https://stackoverflow.com/questions/75067529/whatsapp-web-js-multiple-sessions)

## Ready-made commands

```bash
cd /home/ssi-edi-server/CRM-SSI/CRM_SSI/whatsapp-service
cp .env .env.crm2
sed -i 's/^PORT=.*/PORT=3002/' .env.crm2
sed -i 's/^WHATSAPP_CLIENT_ID=.*/WHATSAPP_CLIENT_ID=crm-whatsapp-2/' .env.crm2

sudo tee /etc/systemd/system/crm-whatsapp-2.service > /dev/null <<'EOF'
[Unit]
Description=CRM WhatsApp service 2
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ssi-edi-server/CRM-SSI/CRM_SSI/whatsapp-service
EnvironmentFile=/home/ssi-edi-server/CRM-SSI/CRM_SSI/whatsapp-service/.env.crm2
Environment=NODE_ENV=production
ExecStart=/usr/bin/node src/server.js
Restart=always
RestartSec=5
User=ssi-edi-server
Group=ssi-edi-server

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now crm-whatsapp-2.service
sudo journalctl -u crm-whatsapp-2.service -f
```

Before you start it, check in your code that `LocalAuth` is initialized with `clientId: whatsappClientId`; otherwise both services may still try to reuse the same auth folder.