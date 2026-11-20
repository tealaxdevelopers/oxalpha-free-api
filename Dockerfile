FROM python:3.12-slim

WORKDIR /app

# Install system deps for Camoufox / Playwright
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxrandr2 libgbm1 libasound2 libpango-1.0-0 libpangocairo-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Camoufox browser binary
RUN python -m camoufox fetch || true

COPY . .

EXPOSE 8080

CMD ["python", "server.py"]
