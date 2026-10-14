FROM debian:bookworm-slim AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gnucobol build-essential \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY cobol ./cobol
COPY build.sh ./build.sh
RUN bash build.sh

FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends python3 libcob4 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --system --uid 10001 --create-home hostregion \
    && mkdir -p /data && chown hostregion:hostregion /data
WORKDIR /app
COPY --from=builder /app/build ./build
COPY hostbridge ./hostbridge
COPY config ./config
COPY db/migrations ./db/migrations
COPY run.sh ./run.sh
ENV BIND=0.0.0.0 PORT=8082 HOST_DATA_DIR=/data PYTHONPATH=/app
USER hostregion
EXPOSE 8082
HEALTHCHECK --interval=15s --timeout=3s CMD python3 -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8082/health', timeout=2)" || exit 1
ENTRYPOINT ["bash", "./run.sh"]
