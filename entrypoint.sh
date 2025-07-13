#!/bin/bash
set -e

# MySanta Recommendation Engine Entrypoint Script
# Supports multiple startup modes via APP_MODE environment variable

echo "🚀 Starting MySanta Recommendation Engine..."
echo "📋 Mode: ${APP_MODE:-server}"
echo "🌍 Environment: ${APP_ENV:-development}"

case "${APP_MODE:-server}" in
    "server")
        echo "🖥️  Starting FastAPI server..."
        if [ "${APP_ENV:-development}" = "development" ]; then
            echo "🔧 Development mode with hot reload enabled"
            exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
        else
            echo "🏭 Production mode"
            exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 1
        fi
        ;;
    
    "worker")
        echo "⚙️  Starting background worker..."
        exec python worker.py
        ;;
    
    "oneshot")
        echo "🎯 Running one-shot data sync..."
        exec python full_sync.py
        ;;
    
    "test")
        echo "🧪 Running tests..."
        exec python -m pytest tests/ -v
        ;;
    
    *)
        echo "❌ Unknown APP_MODE: ${APP_MODE}"
        echo "Valid modes: server, worker, oneshot, test"
        exit 1
        ;;
esac