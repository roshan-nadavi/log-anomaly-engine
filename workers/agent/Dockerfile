FROM python:3.12-slim

WORKDIR /app

COPY workers/agent/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY workers/common ./common
COPY workers/agent/*.py ./

CMD ["python", "main.py"]
