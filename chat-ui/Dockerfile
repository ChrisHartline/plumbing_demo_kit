# Same recipe as deploy/Dockerfile, with one change that matters on Kubernetes:
# the user has a NUMERIC id. A pod that says runAsNonRoot can't verify a name like "appuser".
FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app.py ./
COPY static ./static

RUN useradd --create-home --uid 10001 appuser
USER 10001

EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
