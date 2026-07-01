FROM python:3.12-slim

# Install library sistem yang dibutuhkan pyzbar
RUN apt-get update && \
    apt-get install -y libzbar0 libzbar-dev && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "test:app"]