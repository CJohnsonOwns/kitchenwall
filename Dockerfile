FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
# tzdata so TZ in docker-compose.yml gives the right local time for the calendar
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
COPY deploy/add_user.py deploy/set_secrets.py ./deploy/

# Runs as uid 1000; ./data and ./.env on the host must be writable by that uid.
RUN useradd --uid 1000 --no-create-home kitchenwall && mkdir -p /app/data && chown kitchenwall /app/data
USER kitchenwall

EXPOSE 8000
HEALTHCHECK --interval=1m --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/login', timeout=4)"
CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--no-server-header", "--timeout-keep-alive", "5"]
