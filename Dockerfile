# syntax=docker/dockerfile:1

# Build stage: resolve the locked dependencies into a virtual environment.
FROM python:3.14-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.13.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
RUN uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN uv sync --locked --no-dev --no-editable

# Runtime stage: the environment, the data files and a database built from them.
FROM python:3.14-slim
RUN useradd --system --uid 10001 --home-dir /app app
WORKDIR /app
ENV PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=fuelroute.settings \
    FUELROUTE_DATA_DIR=/app/data \
    DATABASE_PATH=/app/var/fuelroute.sqlite3
COPY --from=build /app/.venv /app/.venv
COPY manage.py ./
COPY data ./data
# The station data is static, so the database is built once here and only read at runtime.
RUN mkdir var \
    && python manage.py migrate --no-input \
    && python manage.py import_stations \
    && chown -R app:app var
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)"]
# The control socket is not used, and the read-only file system has no place for it.
CMD ["gunicorn", "fuelroute.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "2", "--threads", "4", "--access-logfile", "-", "--no-control-socket"]
