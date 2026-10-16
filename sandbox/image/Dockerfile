# Runner image for python_run (ADR-003). Built on the sandbox host:
#   docker build -t harness-sandbox:py312 sandbox/image
FROM python:3.12-slim
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt \
    && useradd --uid 10001 --no-create-home --home-dir /work sandbox
ENV MPLBACKEND=Agg MPLCONFIGDIR=/work/.matplotlib PYTHONDONTWRITEBYTECODE=1
USER 10001
WORKDIR /work
CMD ["python", "-I", "-"]
