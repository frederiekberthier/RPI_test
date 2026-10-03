#!/usr/bin/env bash
# Toont het scherm van de tester schermvullend in Chromium. Wordt gestart door de autostart van labwc.
# Herstart de browser als hij stopt, en wacht eerst tot de webdienst antwoordt.
URL="${RPITEST_URL:-http://127.0.0.1:8080/}"

BROWSER="$(command -v chromium || command -v chromium-browser || true)"
if [ -z "$BROWSER" ]; then
  echo "kiosk: chromium niet gevonden" >&2
  exit 1
fi

until curl -fsS -o /dev/null "$URL"; do
  sleep 1
done

while true; do
  # Een vers profiel bij elke start: geen 'sessie herstellen'-melding na een stroomuitval.
  "$BROWSER" --kiosk --noerrdialogs --disable-infobars --no-first-run --disable-session-crashed-bubble \
    --disable-translate --check-for-update-interval=31536000 --overscroll-history-navigation=0 \
    --password-store=basic --ozone-platform-hint=auto \
    --user-data-dir=/tmp/rpitest-kiosk "$URL"
  sleep 2
done
