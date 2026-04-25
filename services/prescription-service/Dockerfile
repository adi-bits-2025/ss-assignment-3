FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /data/db
ENV DATA_DIR=/data/db
EXPOSE 5004
CMD ["python", "app.py"]
