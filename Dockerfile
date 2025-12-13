# ---------------------------------------------------------------------
# FIX 1: Use a Stable Python Version (3.12)
# ---------------------------------------------------------------------
FROM python:3.12-slim

# Set the working directory
WORKDIR /app

# ---------------------------------------------------------------------
# FIX 2 & 3: Install necessary system build dependencies
# ---------------------------------------------------------------------
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------
# FIX 4: Copy requirements and install packages
# ---------------------------------------------------------------------
COPY requirements.txt .
RUN pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# ---------------------------------------------------------------------
# FIX 5 (Runtime): Copy all application code
# ---------------------------------------------------------------------
COPY . /app 

# ---------------------------------------------------------------------
# FIX 6 (Runtime): Define the startup command using the Render PORT env var
# ---------------------------------------------------------------------
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "${PORT}"]
