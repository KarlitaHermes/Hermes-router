FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY router.py .

# Port 8319 serves the API (/v1/*), /health, /metrics, and the built-in
# monitoring dashboard (open http://localhost:8319/ in a browser).
EXPOSE 8319

CMD ["python", "router.py"]
