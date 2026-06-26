FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY monthly_order_ingestion ./monthly_order_ingestion
COPY scripts ./scripts

CMD ["python", "scripts/run_monthly_order_ingestion.py", "--mode", "delta"]
