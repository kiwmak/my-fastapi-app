FROM python:3.11 

# Cài đặt system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    libpq-dev \
    python3-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt


# Copy toàn bộ source code vào container
COPY . /app
WORKDIR /app

# Mở port nếu dùng web service
EXPOSE 8000

# Command chạy app
CMD ["python", "main.py"]
