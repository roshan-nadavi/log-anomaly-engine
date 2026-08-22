FROM python:3.12-slim

WORKDIR /app

COPY workers/aggregator/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workers/common ./common
COPY workers/aggregator/main.py .

CMD ["python", "main.py"]
