# Server Commands

Personal cheat-sheet for operating CRM_SSI on the production server.

## Quick Deploy: Rebuild + Restart + Migrate

The original copy-paste block — rebuild the backend, restart it, apply
migrations, confirm the migration applied, then rebuild the full stack.
Each command is explained individually in the sections below.

```bash
docker compose build --no-cache backend
docker compose up -d --force-recreate backend
docker compose exec backend alembic heads
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
docker compose up --build -d
```

## Backend: Build & Deploy

```bash
# Rebuild the backend image from scratch, ignoring the layer cache
# (use after changing requirements.txt or anything Docker normally caches)
docker compose build --no-cache backend

# Recreate and restart the backend container using the freshly built image
docker compose up -d --force-recreate backend

# Rebuild + restart the ENTIRE stack (db, backend, frontend, quotation-*, nginx)
docker compose up --build -d

# Same as above, but via the systemd unit that wraps `docker compose up/down`
# for the whole stack instead of running compose manually
sudo systemctl restart crm-ssi

# Rebuild the Quotation Manager sub-app (separate FastAPI + React app under
# quotation-manager/) the same way as backend, when only that app changed
docker compose build --no-cache quotation-backend
docker compose up -d --force-recreate quotation-backend
docker compose build --no-cache quotation-frontend
docker compose up -d --force-recreate quotation-frontend
```

## Database Migrations (Alembic)

```bash
# Show the latest migration(s) defined in code (the target you're migrating to)
docker compose exec backend alembic heads

# Show the migration currently applied to the DB — check BEFORE upgrading
docker compose exec backend alembic current

# Apply all pending migrations up to the latest head
docker compose exec backend alembic upgrade head

# Check current again AFTER upgrading, to confirm it actually moved
docker compose exec backend alembic current

# Roll back the single most recent migration (use if a migration breaks something)
docker compose exec backend alembic downgrade -1

# List the full migration history, in order
docker compose exec backend alembic history
```

## Status Checks

Check what's actually running before you restart or dig into logs.

```bash
# List all compose containers and their state/health
docker compose ps

# Check the systemd-managed services (WhatsApp instances + full stack wrapper)
sudo systemctl status crm-whatsapp
sudo systemctl status crm-whatsapp-2
sudo systemctl status crm-ssi
```

## Logs

```bash
# NOTE: "whatsapp-service" is an UNRELATED project (SwiftHK), not CRM_SSI —
# easy to confuse with crm-whatsapp below. Double-check before using it.
journalctl -u whatsapp-service -f

# CRM_SSI WhatsApp instance for the EDI account
journalctl -u crm-whatsapp -f

# CRM_SSI WhatsApp instance for the SSI account
journalctl -u crm-whatsapp-2 -f

# Containerized services have no systemd unit of their own, so tail them
# via docker compose instead of journalctl
docker compose logs -f backend
docker compose logs -f nginx
docker compose logs -f quotation-backend
```

## Service Restarts

```bash
# NOTE: this is the unrelated SwiftHK project, not CRM_SSI — confirm this is
# really the one you meant to restart before running it
sudo systemctl restart whatsapp-service

# CRM_SSI WhatsApp instance for the SSI account
sudo systemctl restart crm-whatsapp-2

# CRM_SSI WhatsApp instance for the EDI account
sudo systemctl restart crm-whatsapp
```

## Other Useful Commands (suggested, not currently in use)

```bash
# Dump the Postgres database to a local backup file before risky operations
# (e.g. before running a migration). No backup command exists in the repo
# today, so replace <user> with the actual DB user before running.
docker compose exec db pg_dump -U <user> crm > backup.sql

# Validate the nginx config for syntax errors before reloading it
docker compose exec nginx nginx -t

# Reload nginx without dropping connections, after editing nginx/default.conf
docker compose exec nginx nginx -s reload
```
