FROM node:22-bookworm-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --include=dev
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home harness
COPY app.py research.py identity.py memory.py compaction.py backend.py client_tools.py telemetry.py profiles.yaml ./
COPY memory_ui.py chat_memory.py skill_loader.py chat_ui.py conversation_store.py vault_mcp.py sessions.py mcp_registry.py mcp_client.py code_mcp.py web_mcp.py rag_tool.py oidc.py number_check.py documents.py ./
COPY --from=frontend /frontend/dist ./frontend/dist
COPY skills ./skills
COPY memory_ui ./memory_ui
COPY demo_notes ./demo_notes
COPY prompts ./prompts
COPY scripts ./scripts
RUN mkdir /app/chat-data && chown 10001:10001 /app/chat-data
# The commit this image was built from, shown on each tool answer's run line.
ARG HARNESS_VERSION=unknown
ENV HARNESS_VERSION=$HARNESS_VERSION
USER 10001
EXPOSE 8200
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8200", "--no-access-log"]
