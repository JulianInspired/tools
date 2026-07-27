#!/bin/bash
# Double-click this file to launch QR GENERATOR.
# It starts the Streamlit server, opens your browser, and stays running
# until you close the Terminal window or press Ctrl+C.
#
# NOTE: this tool shares the ImageScraper virtualenv (sibling folder) so the
# two tools don't need duplicate installs. If you move this folder, create a
# local venv instead:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV_DIR="$PROJECT_DIR/../ImageScraper/.venv"
[ -x "$PROJECT_DIR/.venv/bin/streamlit" ] && VENV_DIR="$PROJECT_DIR/.venv"
LOG_FILE="$PROJECT_DIR/launcher.log"
PORT=8502

cd "$PROJECT_DIR" || exit 1

if [ ! -x "$VENV_DIR/bin/streamlit" ]; then
    echo "No usable virtualenv found (looked in ./.venv and ../ImageScraper/.venv)."
    echo "Create one with:"
    echo "  python3 -m venv .venv"
    echo "  .venv/bin/pip install -r requirements.txt"
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
echo "  QR GENERATOR  ·  House of Brands tool module"
echo "  http://localhost:$PORT"
echo "  Close this window or press Ctrl+C to stop."
echo "===================================================="

exec "$VENV_DIR/bin/streamlit" run "$PROJECT_DIR/app.py" \
    --server.headless true \
    --server.port "$PORT" \
    --browser.gatherUsageStats false 2>&1 | tee "$LOG_FILE"
