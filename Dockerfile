FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY router.py .

EXPOSE 8319

CMD ["python", "router.py"]
