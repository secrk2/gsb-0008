FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# 容器内等待 PG -> 建表 -> 幂等种子 -> 起服务（固定 7101）
RUN chmod +x ./entrypoint.sh
EXPOSE 7101
ENTRYPOINT ["./entrypoint.sh"]
