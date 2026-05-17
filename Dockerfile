FROM python:3.11-slim

WORKDIR /app

COPY requirements-lock.txt .
RUN pip install --no-cache-dir -r requirements-lock.txt

COPY . .

ENV ENV=production
ENV BRIEF_STORE_BACKEND=postgres
ENV AUTH_MODE=jwks
ENV IDEMPOTENCY_STORE_BACKEND=sqlite

EXPOSE 8000

CMD ["uvicorn", "directora.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
