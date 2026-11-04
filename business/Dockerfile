FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    STATE_PATH=/data/business.sqlite3
WORKDIR /app
COPY business/*.py /app/business/
RUN mkdir -p /data && chmod 700 /data
CMD ["python", "-m", "business.bot"]
