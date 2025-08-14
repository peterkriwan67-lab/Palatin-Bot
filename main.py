import os
import time
import requests
from datetime import datetime
from flask import Flask
import threading

# ---------------------------
# Mini-Webserver für Keep-Alive
# ---------------------------
app = Flask(__name__)


@app.route("/")
def home():
    return "SEC Bot läuft"


def run():
    app.run(host="0.0.0.0", port=8080)


def keep_alive():
    t = threading.Thread(target=run)
    t.start()


# ---------------------------
# Deine Bot-Logik
# ---------------------------

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")


def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": message}
    try:
        requests.post(url, json=payload)
    except Exception as e:
        print(f"[Fehler beim Senden an Telegram] {e}")


def check_sec_filings():
    url = "https://data.sec.gov/submissions/CIK0000910267.json"  # Palatin CIK
    headers = {"User-Agent": "MyBot/1.0 (your_email@example.com)"}
    try:
        r = requests.get(url, headers=headers)
        if r.status_code == 200:
            data = r.json()
            recent = data.get("filings", {}).get("recent", {})
            if recent:
                accession_numbers = recent.get("accessionNumber", [])
                if accession_numbers:
                    last_filing = accession_numbers[0]
                    return last_filing
    except Exception as e:
        print(f"[Fehler beim Abrufen der SEC-Daten] {e}")
    return None


def main_loop():
    last_seen_filing = None
    while True:
        try:
            latest_filing = check_sec_filings()
            if latest_filing and latest_filing != last_seen_filing:
                last_seen_filing = latest_filing
                msg = f"Neue SEC-Meldung entdeckt: {latest_filing}"
                print(f"[{datetime.now()}] {msg}")
                send_telegram_message(msg)
        except Exception as e:
            print(f"[Bot-Fehler] {e}")
        time.sleep(300)  # alle 5 Minuten prüfen


# ---------------------------
# Startpunkt
# ---------------------------
if __name__ == "__main__":
    keep_alive()  # hält den Bot im Free-Plan wach
    main_loop()
