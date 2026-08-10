FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
RUN pip install --no-cache-dir uv==0.6.14

COPY pyproject.toml uv.lock ./
COPY alembic.ini ./
COPY backend ./backend
RUN uv sync --frozen --no-dev --no-editable

EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "pmaa_web.main:app", "--host", "0.0.0.0", "--port", "8000"]
