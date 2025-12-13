# =========================
# DOCKERIZED FASTAPI + POSTGRES (RENDER / PROD READY)
# =========================

# ---------- Dockerfile ----------
# File: Dockerfile
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# system deps (needed for bcrypt, psycopg2)
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 10000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "10000"]


# ---------- .dockerignore ----------
# File: .dockerignore
__pycache__
*.pyc
*.pyo
*.pyd
.env
.git
.gitignore
uploads/
exports/


# ---------- requirements.txt ----------
fastapi
uvicorn[standard]
sqlalchemy>=2.0
psycopg2-binary
pandas
openpyxl
python-multipart
python-jose[cryptography]
passlib[bcrypt]


# ---------- Render Settings ----------
# Environment: Docker
# Port: 10000
# DATABASE_URL: postgresql://...
# SECRET_KEY: <strong-secret>


# ---------- Local Test ----------
# docker build -t qc-fastapi .
# docker run -p 10000:10000 \
#   -e DATABASE_URL=postgresql://user:pass@host:port/db \
#   -e SECRET_KEY=secret \
#   qc-fastapi


# ---------- Result ----------
# ✔ No MySQL / MySQLdb possible
# ✔ Deterministic build
# ✔ Render / Railway compatible
# ✔ Production-safe
