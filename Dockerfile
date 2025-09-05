# =================
#   Builder stage
# =================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Configure the Python directory so it is consistent
ENV UV_PYTHON_INSTALL_DIR=/python

# Only use the managed Python version
ENV UV_PYTHON_PREFERENCE=only-managed

# Install Python before the project for caching
RUN uv python install 3.12

WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
COPY minitap /app/minitap
COPY pyproject.toml pyrightconfig.json uv.lock \
    README.md CONTRIBUTING.md llm-config.defaults.jsonc LICENSE \
    /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev


# =================
#    Final stage
# =================
FROM debian:bookworm-slim

ARG MAESTRO_VERSION=1.41.0

# Install required dependencies for UV & adb
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl ca-certificates adb unzip wget && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Install JRE
RUN apt-get update && \
    apt-get install -y --no-install-recommends default-jre && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# Use non-root user
RUN useradd -m -s /bin/bash --create-home mobile-use && \
    chown -R mobile-use:mobile-use /opt/ && \
    mkdir -p /home/mobile-use/.android && \
    chown -R mobile-use:mobile-use /home/mobile-use/.android
USER mobile-use

# Download & install Maestro
RUN mkdir -p /opt/maestro && \
    wget -q -O /tmp/${MAESTRO_VERSION} "https://github.com/mobile-dev-inc/maestro/releases/download/cli-${MAESTRO_VERSION}/maestro.zip" && \
    unzip -q /tmp/${MAESTRO_VERSION} -d /opt/ && \
    rm /tmp/${MAESTRO_VERSION}
ENV PATH="/opt/maestro/bin:${PATH}"

WORKDIR /app

# Copy the Python version
COPY --from=builder --chown=python:python /python /python

# Copy the application from the builder
COPY --from=builder --chown=app:app /app /app
ENV PATH="/app/.venv/bin:$PATH"

COPY --chown=mobile-use:mobile-use docker-entrypoint.sh /app/docker-entrypoint.sh
ENTRYPOINT ["/app/docker-entrypoint.sh"]
