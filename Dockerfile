FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home harness
COPY app.py research.py identity.py memory.py compaction.py backend.py client_tools.py telemetry.py profiles.yaml ./
COPY profiles.portable.yaml ./
COPY memory_ui.py chat_memory.py ./
COPY memory_ui ./memory_ui
COPY demo_notes ./demo_notes
COPY prompts ./prompts
COPY scripts ./scripts
USER 10001
EXPOSE 8200
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8200", "--no-access-log"]
