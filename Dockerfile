FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir requests py-clob-client

COPY phase1_bot.py .

# Persist the SQLite database via a mounted volume at /data
ENV POLYBOT_DB_PATH=/data/polybot_trades.db

ENTRYPOINT ["python3", "phase1_bot.py"]
CMD ["--loop", "--interval", "300", "--min-edge", "0.03", "--db", "/data/polybot_trades.db"]
