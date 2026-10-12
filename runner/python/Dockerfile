FROM python:3.12-slim
RUN useradd --create-home --uid 10001 verifier
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY runner.py ./runner.py
RUN mkdir -p /work && chown -R 10001:10001 /work /app
USER 10001
ENV PYTHONUNBUFFERED=1
ENTRYPOINT ["python", "/app/runner.py"]
