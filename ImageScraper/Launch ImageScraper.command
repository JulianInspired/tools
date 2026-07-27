#!/bin/bash
# Double-click this file to launch IMAGE SCRAPER.
# It starts the Streamlit server, opens your browser, and stays running
# until you close the Terminal window or press Ctrl+C.

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$PROJECT_DIR/launcher.log"
PORT=8501

cd "$PROJECT_DIR" || exit 1

if [ ! -x "$PROJECT_DIR/.venv/bin/streamlit" ]; then
    echo "Virtual environment is missing or incomplete."
    echo "Run these commands in this folder, then try again:"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r requirements.txt"
    echo "  .venv/bin/playwright install chromium"
    sleep 15
    exit 1
fi

EXISTING=$(lsof -ti:$PORT 2>/dev/null || true)
if [ -n "$EXISTING" ]; then
    echo "Stopping existing process on port $PORT (pid $EXISTING)..."
    kill -9 $EXISTING 2>/dev/null || true
    sleep 1
fi

# Open the browser once the server is up.
(
    for i in {1..40}; do
        sleep 1
        if curl -s -o /dev/null "http://localhost:$PORT"; then
            open "http://localhost:$PORT"
            exit 0
        fi
    done
) &

echo "===================================================="
echo "  IMAGE SCRAPER  ·  House of Brands tool module"
echo "  http://localhost:$PORT"
echo "  Close this window or press Ctrl+C to stop."
echo "===================================================="

exec "$PROJECT_DIR/.venv/bin/streamlit" run "$PROJECT_DIR/app.py" \
    --server.headless true \
    --server.port "$PORT" \
    --browser.gatherUsageStats false 2>&1 | tee "$LOG_FILE"
