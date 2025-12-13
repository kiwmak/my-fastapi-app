# ---------------------------------------------------------------------
# FIX 1: Use a Stable Python Version (e.g., 3.12) for better compatibility
# ---------------------------------------------------------------------
FROM python:3.12-slim

# Set the working directory for the application
WORKDIR /app

# ---------------------------------------------------------------------
# FIX 2 & 3 (psycopg2 & pandas): Install necessary system build dependencies
#   - build-essential: General compiler tools (needed for numpy/pandas compilation)
#   - libpq-dev: PostgreSQL client libraries/headers (needed for psycopg2 compilation)
# ---------------------------------------------------------------------
RUN apt-get update \
    # Install tools needed for compiling C extensions
    && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    # Clean up APT cache to reduce final image size
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------
# FIX 4: Copy the requirements file before installing
# ---------------------------------------------------------------------
# Cập nhật pip, wheel và cài dependencies
COPY requirements.txt .

# Install Python packages
# --no-cache-dir is used to prevent pip from storing downloaded wheels, saving space
RUN pip install --upgrade pip wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application source code here (assuming 'app' folder)
# COPY . . 

# Define the command to run your application
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
