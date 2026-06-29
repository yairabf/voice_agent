FROM python:3.11-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VOICE_RUNTIME_PORT=8088 \
    HERMES_INTEGRATION_MODE=fake

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8088

CMD ["python", "-m", "voice_agent"]
