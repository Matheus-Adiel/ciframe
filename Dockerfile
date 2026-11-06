FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV DECIFRAME_DB=/data/deciframe.db
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "main:app"]
