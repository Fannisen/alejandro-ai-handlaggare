FROM python:3.11-slim

WORKDIR /app

# Installera beroenden
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Kopiera källkod
COPY . .

# Exponera webhook-port
EXPOSE 8000

# Starta webhook-servern (som i sin tur kör polling som backup)
CMD ["python", "webhook_server.py"]
