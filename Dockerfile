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

COPY pixi.toml pixi.lock ./

RUN pixi install --locked --no-progress \
    && pixi clean cache --yes

COPY pyproject.toml README.md MANIFEST.in ./
COPY assets ./assets
COPY src ./src
COPY vendor ./vendor
COPY workflows ./workflows

RUN python -m pip install --no-deps . \
    && chmod +x workflows/*.sh

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app \
    && chown -R app:app /app

EXPOSE 8050

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import ssl, urllib.request; from hapapp_python.env import load_env; load_env(); from hapapp_python import config; scheme = 'https' if config.SSL_CONTEXT else 'http'; context = ssl._create_unverified_context() if config.SSL_CONTEXT else None; urllib.request.urlopen(f'{scheme}://127.0.0.1:{config.APP_PORT}/', context=context, timeout=3)"

USER app

CMD ["hapapp-online", "--no-open"]
