docker compose build --no-cache backend
docker compose up -d --force-recreate backend
docker compose exec backend alembic heads
docker compose exec backend alembic current
docker compose exec backend alembic upgrade head
docker compose exec backend alembic current