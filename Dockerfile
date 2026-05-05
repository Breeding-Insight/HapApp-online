ARG PIXI_VERSION=0.67.2
ARG DOCKER_PLATFORM=linux/amd64
FROM --platform=${DOCKER_PLATFORM} ghcr.io/prefix-dev/pixi:${PIXI_VERSION}

WORKDIR /app

ENV HAPAPP_HOST=0.0.0.0 \
    HAPAPP_PORT=8050 \
    HAPAPP_DEBUG=0 \
    PATH=/app/.pixi/envs/default/bin:${PATH} \
    PIXI_NO_PROGRESS=true \
    PYTHONUNBUFFERED=1

COPY pixi.toml pixi.lock pyproject.toml README.md MANIFEST.in ./
COPY assets ./assets
COPY src ./src
COPY vendor ./vendor
COPY workflows ./workflows

RUN pixi install --locked --no-progress \
    && pixi clean cache --yes \
    && chmod +x workflows/*.sh

EXPOSE 8050

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('HAPAPP_PORT', '8050') + '/', timeout=3)"

CMD ["hapapp-python", "--no-open"]
