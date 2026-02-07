#!/bin/bash
# Script per avviare l'API FastAPI

echo "🚀 Avvio AI System API..."
echo ""

# Check se Docker è running
if ! docker ps &>/dev/null; then
    echo "❌ Docker non è in esecuzione!"
    echo "   Avvia Docker Desktop e riprova."
    exit 1
fi

# Check se i servizi sono up
if ! docker ps | grep -q "ai-system-postgres"; then
    echo "⚠️  Servizi Docker non avviati. Avvio..."
    docker-compose up -d
    echo "⏳ Attendo 10 secondi per l'avvio dei servizi..."
    sleep 10
fi

# Check Python dependencies
if ! python3 -c "import fastapi" &>/dev/null; then
    echo "⚠️  Dipendenze Python mancanti. Installazione..."
    pip3 install fastapi uvicorn sqlalchemy psycopg2-binary --quiet --user
fi

echo "✅ Tutto pronto!"
echo ""
echo "📡 Avvio FastAPI su http://localhost:8000"
echo "📚 Docs: http://localhost:8000/docs"
echo ""
echo "⏹️  Per fermare: Ctrl+C"
echo ""

# Avvia FastAPI
python3 main.py
