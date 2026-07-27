FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY quotation-manager/backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY quotation-manager/backend /app/backend
WORKDIR /app/backend

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
