FROM python:3.11-slim

# System deps required by OpenCV
RUN apt-get update && apt-get install -y \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements-webhook.txt .
RUN pip install --no-cache-dir -r requirements-webhook.txt

COPY . .

EXPOSE 10000

CMD ["sh", "-c", "gunicorn wsgi:app --bind 0.0.0.0:${PORT:-10000}"]
