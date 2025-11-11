# Chọn image Python 3.13 chính thức
FROM python:3.13-slim

# Cập nhật hệ thống và cài build-essential, gcc, g++
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    g++ \
    libffi-dev \
    libbz2-dev \
    liblzma-dev \
    libssl-dev \
    libsqlite3-dev \
    git \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy file requirements
COPY requirements.txt .

# Cập nhật pip, wheel và cài dependencies
RUN pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy toàn bộ source code vào container
COPY . /app
WORKDIR /app

# Mở port nếu dùng web service
EXPOSE 8000

# Command chạy app
CMD ["python", "app.py"]
