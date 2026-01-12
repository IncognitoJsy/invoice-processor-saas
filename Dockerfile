FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs uploads temp_uploads integration_data/queue

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

# Start gunicorn (no auto-migration)
CMD gunicorn --bind 0.0.0.0:8000 --access-logfile - --error-logfile - --log-level debug wsgi:app
