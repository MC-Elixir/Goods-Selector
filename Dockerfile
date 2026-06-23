FROM python:3.12-slim

# 系统依赖：Playwright Chromium 需要的库
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget \
    ca-certificates \
    fonts-liberation \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libx11-xcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxrandr2 \
    xdg-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python 依赖（利用 Docker 缓存层）
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Playwright Chromium 浏览器
RUN playwright install chromium

# 应用代码
COPY . .

# 数据目录（通过 volume 挂载持久化）
RUN mkdir -p /app/data/cache /app/data/exports /app/data/images

ENTRYPOINT ["python", "main.py"]
