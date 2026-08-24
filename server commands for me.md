docker compose build --no-cache backend
docker compose up -d --force-recreate backend
docker compose exec backend alembic heads
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current
docker compose up --build -d

journalctl -u crm-whatsapp -f
journalctl -u crm-whatsapp-2 -f

sudo systemctl restart crm-whatsapp-2
sudo systemctl restart crm-whatsapp