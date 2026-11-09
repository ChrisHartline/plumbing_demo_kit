# The whole "container" idea in eight lines:
# a known OS + a known Python + pinned packages + our code + one start command.
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY plumbing_agent.py main.py ./

# Don't run as root inside the container.
RUN useradd --create-home appuser
USER appuser

# Cloud Run tells the container which port to listen on via $PORT (default 8080).
CMD exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8080}
