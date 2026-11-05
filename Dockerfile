FROM python:3.11-slim

WORKDIR /app

# Installa dipendenze di sistema minime
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copia i requisiti e installa le dipendenze Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia il codice sorgente
COPY . .

# Variabili d'ambiente per Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Avvio del bot
CMD ["python", "telegram_bot.py"]
