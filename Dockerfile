# syntax=docker/dockerfile:1
#
# One image: the API, the built interface, and the sample corpus.
#
# The interface is served by the API process rather than by a separate static host, which
# is why there is one image and not two (implementation.md section 10, app/web.py). One
# origin means no CORS surface, one deployment to configure, and one thing to keep awake on
# a free tier.
#
# Build from the REPOSITORY ROOT, not from server/:
#     docker build -t distill .
#
# Decision D86.

# ---------------------------------------------------------------------------
# 1. Build the interface
# ---------------------------------------------------------------------------
FROM node:22-alpine AS client

WORKDIR /build

# Manifests first, so a change to a component does not reinstall node_modules.
COPY client/package.json client/package-lock.json ./
RUN npm ci

COPY client/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# 2. The application
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# tesseract-ocr is the one system package this application cannot do without: pages with no
# text layer are read by OCR (decision D3), and pytesseract shells out to this binary. It is
# also the reason this is a Dockerfile and not a buildpack, since no buildpack lets you
# install a system package.
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# uv from PyPI rather than the published image, so its version is pinned in the same
# place as everything else and the build has one fewer registry to depend on.
RUN pip install --no-cache-dir uv==0.12.9

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

# Dependencies as their own layer, from the lock file, so that editing application code
# does not re-resolve and re-download the world.
COPY server/pyproject.toml server/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY server/ ./
COPY samples/ /app/samples/
COPY --from=client /build/dist /app/client-dist

# Migrations run before the server starts, with a retry: see the script.
COPY docker-entrypoint.sh /app/docker-entrypoint.sh
RUN chmod +x /app/docker-entrypoint.sh

# Defaults that describe THIS image rather than a laptop. Everything secret, and everything
# that differs between one deployment and the next, is passed in at run time.
ENV ENVIRONMENT=production \
    LOG_JSON=true \
    STORAGE_BACKEND=postgres \
    CLIENT_DIST_DIR=/app/client-dist \
    SAMPLES_DIR=/app/samples \
    LLM_PROVIDER=gemini \
    PORT=8000

# LLM_PROVIDER=gemini above means a deployment with no GEMINI_API_KEY refuses to start,
# with the validator in app/config.py saying so. That is deliberate. The alternative is a
# container that boots happily and serves recorded fixtures, which looks exactly like a
# working product until someone asks it a question it has never been asked.

# Not root. The application writes nothing to disk that matters (storage is the database),
# so it does not need to own anything but its own virtual environment.
RUN useradd --create-home --uid 10001 distill && chown -R distill:distill /app
USER distill

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen(f\"http://127.0.0.1:{os.environ.get('PORT','8000')}/healthz\").read()"

CMD ["/app/docker-entrypoint.sh"]
