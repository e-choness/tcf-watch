FROM python:3.12-slim

# Non-root for hygiene
RUN useradd --create-home --uid 1000 watcher
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tcfwatch/ tcfwatch/

RUN mkdir -p /data && chown watcher:watcher /data
USER watcher
VOLUME ["/data"]

# Healthcheck: state files must be fresher than 3 poll intervals
HEALTHCHECK --interval=10m --timeout=10s --retries=3 \
  CMD python -c "import json,glob,sys,time,datetime as dt; \
files=glob.glob('/data/*.json'); \
sys.exit(0 if not files else (0 if all( \
 (time.time()-__import__('os').path.getmtime(f)) < 5400 for f in files) else 1))"

ENTRYPOINT ["python", "-m", "tcfwatch"]
CMD ["run"]
