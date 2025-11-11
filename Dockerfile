# Base image Python 3.13 slim
FROM python:3.13-slim

WORKDIR /app

# Cài các tool cần thiết để build pandas
RUN apt-get update && apt-get install -y \
    build-essential \
    ninja-build \
    python3-dev \
    cython3 \
    && rm -rf /var/lib/apt/lists/*

# Copy code
COPY . .

# Upgrade pip và cài requirements
RUN pip install --upgrade pip wheel
RUN pip install -r requirements.txt

# Expose port
EXPOSE 10000

# Chạy uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]
