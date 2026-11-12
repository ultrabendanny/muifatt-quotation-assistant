# Container image for Cloud Run (Day 1 p.80: containerised, scales to zero).
# Do not bake .env into the image. Inject GOOGLE_API_KEY at runtime.
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PORT=8080
EXPOSE 8080

CMD streamlit run app.py --server.port=$PORT --server.address=0.0.0.0 --server.headless=true
