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

# Pre-flight check: compila i sorgenti Python per bloccare a monte errori di sintassi/import
RUN python -m py_compile telegram_bot.py config.py services/*.py

# Rendi eseguibile l'entrypoint supervisor
RUN chmod +x entrypoint.sh

# Variabili d'ambiente per Python
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Avvio con Supervisor auto-restart
CMD ["./entrypoint.sh"]
