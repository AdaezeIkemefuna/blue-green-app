FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY log_watcher.py .

CMD ["python", "-u", "log_watcher.py"]