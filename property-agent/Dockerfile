# Property agent service for the sheet's Analyze button (Railway builds this file).
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY agent_app ./agent_app

RUN useradd --create-home agent
USER agent

# Railway sets PORT. Settings: ANTHROPIC_API_KEY, PIVOTAL_SERVICE_TOKEN, optional PIVOTAL_MCP_TOKEN
# (see agent_app/service.py).
CMD ["sh", "-c", "uvicorn --app-dir agent_app --factory service:app_factory --host 0.0.0.0 --port ${PORT:-8000}"]
