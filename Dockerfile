# bylaw as a self-hosted GitHub App: the webhook server (docs/app/deploy.md, ADR 0017).
# Base images are pinned by digest; update the tag and the digest together.

FROM ghcr.io/astral-sh/uv:0.13.1@sha256:4a1f3666816dafadd20ceb71eac9a7d56d7ef30279f7d64048519ab901ada336 AS uv

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
# The same path as in the final image: a virtual environment's scripts name their interpreter by path.
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
# The lock file decides every version, as in the Action (ADR 0009); no dev tools, the app extra only.
RUN uv sync --locked --no-dev --extra app --no-editable --python /usr/local/bin/python3

FROM python:3.13-slim@sha256:70729b46c69b4f1e97c4822c1af3df53a1476cf5ddc6c087c0c10bc3a5678c2f
RUN useradd --system --uid 10001 --user-group --no-create-home --shell /usr/sbin/nologin bylaw
COPY --from=build /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH PYTHONUNBUFFERED=1 BYLAW_APP_HOST=0.0.0.0 PORT=8000
USER 10001:10001
EXPOSE 8000
# The slim image has no curl or wget, so Python itself asks the health endpoint; urlopen fails on
# anything but a 2xx answer.
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:' + os.environ.get('PORT', '8000') + '/healthz', timeout=4)"]
CMD ["bylaw-app"]
