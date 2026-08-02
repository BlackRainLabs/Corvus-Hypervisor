FROM python:3.12-slim-bookworm

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md LICENSE ./
COPY config ./config
COPY src ./src

RUN pip install --no-cache-dir .

ENV CORVUS_USE_TCP=1 \
    CORVUS_TCP_HOST=0.0.0.0 \
    CORVUS_TCP_PORT=4040 \
    CORVUS_MGMT_HOST=0.0.0.0 \
    CORVUS_MGMT_PORT=8080 \
    CORVUS_DB_PATH=/data/corvus.db \
    CORVUS_VM_STATE_DIR=/data/vms \
    CORVUS_API_KEY=dev-api-key

EXPOSE 4040 8080
VOLUME ["/data"]

CMD ["corvus-server"]
