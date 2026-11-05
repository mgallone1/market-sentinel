#!/usr/bin/env bash
# Script di avvio per Market Sentinel AI

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "Virtual environment non trovato. Creazione in corso..."
    python3 -m venv venv
    ./venv/bin/pip install -r requirements.txt
fi

echo "🚀 Avvio Market Sentinel AI..."
./venv/bin/streamlit run app.py --server.port 8501 --server.headless true
