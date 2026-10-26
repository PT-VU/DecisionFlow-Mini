FROM ghcr.io/astral-sh/uv:0.9.26-python3.12-bookworm-slim AS build

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
COPY data/public ./data/public
COPY data/public_v02 ./data/public_v02
COPY local_bridge ./local_bridge
RUN uv sync --frozen --no-dev --extra azure

FROM python:3.12-slim AS runtime

WORKDIR /app
ENV PATH="/app/.venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY --from=build /app/.venv /app/.venv
COPY --from=build /app/src /app/src
COPY --from=build /app/data /app/data
COPY --from=build /app/local_bridge /app/local_bridge
RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app

USER appuser
EXPOSE 8000
CMD ["uvicorn", "decisionflow.api:app", "--host", "0.0.0.0", "--port", "8000"]

