FROM python:3.12-slim

ENV DEBIAN_FRONTEND=noninteractive \
    BROWSER_AGENT_COMMAND=/opt/browser-agent/bin/browser-use

# Base utilities needed by the runtime and Playwright installers.
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "60";\nAcquire::https::Timeout "60";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (layered for cache).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional Browser Assistant dependencies. Keep browser-use in a separate venv
# because it pins fast-moving LLM/browser packages that conflict with the main
# sourcing pipeline environment.
COPY requirements-browser-agent.txt .
RUN python -m venv /opt/browser-agent \
    && /opt/browser-agent/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/browser-agent/bin/pip install --no-cache-dir -r requirements-browser-agent.txt

# Browsers: Playwright Chromium (1688 matcher) + scrapling patchright
# (default Amazon scraper). install-deps requires the Python package above.
RUN python -m playwright install-deps chromium \
    && python -m playwright install chromium \
    && scrapling install

# Application code (respects .dockerignore).
COPY . .

# Runtime data dirs (mounted volume overlays these).
RUN mkdir -p /app/data/cache /app/data/exports /app/data/images /app/data/logs

# Entrypoint: ensure DB tables exist, then run the requested command.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

EXPOSE 8765 8766
ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["agent-web", "--host", "0.0.0.0", "--port", "8765"]
