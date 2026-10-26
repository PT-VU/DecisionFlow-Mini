FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY data/public ./data/public
COPY data/public_v02 ./data/public_v02
COPY local_bridge ./local_bridge
RUN pip install --no-cache-dir .[azure]

EXPOSE 8000
CMD ["uvicorn", "decisionflow.api:app", "--host", "0.0.0.0", "--port", "8000"]

