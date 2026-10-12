FROM node:24-bookworm-slim
RUN useradd --create-home --uid 10001 verifier
WORKDIR /app
COPY runner.mjs ./runner.mjs
RUN mkdir -p /work && chown -R 10001:10001 /work /app
USER 10001
ENTRYPOINT ["node", "/app/runner.mjs"]
