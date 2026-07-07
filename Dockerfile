FROM python:3.12-slim

# Chromium system libraries (Playwright-managed; replaces hand-maintained apt list).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl fonts-liberation \
    && python -m playwright install-deps chromium \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (layered for cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Browsers: playwright chromium (1688 Playwright matcher) + scrapling patchright
# (default Amazon scraper — the step the old Dockerfile was missing).
RUN python -m playwright install chromium \
    && scrapling install

# Application code (respects .dockerignore).
COPY . .

# Runtime data dirs (mounted volume overlays these).
RUN mkdir -p /app/data/cache /app/data/exports /app/data/images

# Entrypoint: ensure DB tables exist, then run the requested command.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8765
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["agent-web", "--host", "0.0.0.0", "--port", "8765"]
