FROM python:3.12-slim-bookworm
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home worker
COPY --chown=worker:worker app ./app
COPY --chown=worker:worker sample_data ./sample_data
RUN mkdir /app/var && chown worker:worker /app/var
USER worker
CMD ["python", "-m", "app.orchestrator"]
