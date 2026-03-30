# Multi-stage Dockerfile for Discord Trade Bot
# Supports both development and production builds

# =============================================================================
# Stage 1: Base - Common base for all stages
# =============================================================================
FROM python:3.14-slim AS base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 -s /bin/bash botuser

# Set working directory
WORKDIR /app

# =============================================================================
# Stage 2: Builder - Install dependencies
# =============================================================================
FROM base AS builder

# Install uv for fast dependency installation
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install production dependencies
RUN uv sync --frozen --no-dev

# =============================================================================
# Stage 3: Development - For local development with hot-reload
# =============================================================================
FROM base AS development

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Install uv for development
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
ENV PATH="/root/.cargo/bin:$PATH"

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install dev dependencies
RUN uv sync --frozen

# Copy source code (will be overridden by volume mount in dev)
COPY src/ ./src/
COPY config.yaml .env.dist ./

# Copy entrypoint script
COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Set PATH to include virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER botuser

ENTRYPOINT ["/entrypoint.sh"]
CMD ["discord-trade-bot", "all"]

# =============================================================================
# Stage 4: Production - Optimized production image
# =============================================================================
FROM base AS production

# Copy only production virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy source code
COPY src/ ./src/
COPY config.yaml .env.dist ./

# Copy entrypoint and healthcheck scripts
COPY docker/entrypoint.sh /entrypoint.sh
COPY docker/healthcheck.sh /healthcheck.sh
RUN chmod +x /entrypoint.sh /healthcheck.sh

# Create data directory for SQLite database
RUN mkdir -p /app/data && chown -R botuser:botuser /app

# Set PATH to include virtual environment
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
USER botuser

# Health check (will be overridden by docker-compose for specific services)
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD /healthcheck.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["discord-trade-bot", "all"]
