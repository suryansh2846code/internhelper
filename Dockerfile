# Deployed "brain" server (no browser). Railway builds this.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY requirements-server.txt .
RUN pip install -r requirements-server.txt

COPY . .

# Railway sets $PORT
CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
