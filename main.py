import os, time, threading, requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from flask import Flask

# === Secrets ===
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

# === Konfig ===
CIK = "0000911216"  # Palatin Technologies, Inc.
FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar"
    f"?action=getcompany&CIK={CIK}&type=424B&owner=exclude&count=40&output=atom"
)
HEADERS = {
    "User-Agent":
    "SEC-Alert Bot (contact: your-email@example.com)",  # gerne anpassen
    "Accept": "application/atom+xml",
}
CHECK_INTERVAL = 60  # Sekunden
STATE_FILE = "last_entry_id.txt"
SEEN_FILE = "seen_ids.txt"
BERLIN = ZoneInfo("Europe/Berlin")

# === Mini-Webserver (für UptimeRobot) ===
app = Flask(__name__)


@app.route("/")
def home():
    return "SEC Bot läuft", 200


def keep_alive():
    threading.Thread(target=lambda: app.run(host="0.0.0.0", port=8080),
                     daemon=True).start()


# === Helpers ===
def send_telegram(text: str) -> None:
    try:
        requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            json={
                "chat_id": CHAT_ID,
                "text": text
            },
            timeout=15,
        )
    except Exception as e:
        print(f"[Telegram] Fehler: {e}")


def load_last_id() -> str | None:
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            s = f.read().strip()
            return s or None
    except FileNotFoundError:
        return None


def save_last_id(entry_id: str) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            f.write(entry_id or "")
    except Exception as e:
        print(f"[State] Fehler: {e}")


def load_seen_ids() -> set[str]:
    try:
        with open(SEEN_FILE, "r", encoding="utf-8") as f:
            return set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        return set()


def save_seen_ids(ids: set[str]) -> None:
    try:
        # begrenzen, damit die Datei klein bleibt
        keep = list(ids)[-500:] if len(ids) > 500 else list(ids)
        with open(SEEN_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(keep))
    except Exception as e:
        print(f"[Seen] Fehler: {e}")


def parse_updated_utc(s: str) -> datetime:
    if not s:
        return datetime.now(timezone.utc)
    iso = s.replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return datetime.now(timezone.utc)


def fetch_entries() -> list[dict]:
    """Liest alle Entries (neueste zuerst) aus dem Atom-Feed."""
    r = requests.get(FEED_URL, headers=HEADERS, timeout=20)
    r.raise_for_status()
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(r.text)
    out = []
    for e in root.findall("a:entry", ns):
        id_e = e.find("a:id", ns)
        title_e = e.find("a:title", ns)
        link_e = e.find("a:link", ns)
        upd_e = e.find("a:updated", ns)
        entry_id = (id_e.text or "").strip() if id_e is not None else ""
        title = (title_e.text or "").strip() if title_e is not None else ""
        link = (link_e.attrib.get("href")
                if link_e is not None else None) or FEED_URL
        updated = parse_updated_utc((
            upd_e.text or "").strip() if upd_e is not None else "")
        out.append({
            "id": entry_id,
            "title": title,
            "link": link,
            "updated_utc": updated
        })
    return out  # neueste zuerst


def is_relevant_424(title: str) -> bool:
    t = (title or "").upper()
    return ("424B3" in t) or ("424B5" in t)


# === Main-Loop ===
def main_loop():
    print("SEC 424B3/424B5 Bot läuft …")
    send_telegram("✅ SEC-Bot gestartet (Palatin 424B3/424B5, Intervall 60s).")

    last_id = load_last_id()
    seen_ids = load_seen_ids()

    while True:
        try:
            entries = fetch_entries()  # neueste → älteste
            if not entries:
                print("[SEC] Keine Einträge.")
                time.sleep(CHECK_INTERVAL)
                continue

            # Erststart: NICHT alerten, vorhandene Einträge nur merken
            if last_id is None:
                for ent in entries:
                    seen_ids.add(ent["id"])
                save_seen_ids(seen_ids)
                last_id = entries[0]["id"]  # neueste ID
                save_last_id(last_id)
                print(
                    "[Init] Bestehende Einträge markiert; keine Alerts gesendet."
                )
                time.sleep(CHECK_INTERVAL)
                continue

            # Neue Einträge seit letztem Check
            newer = []
            for ent in entries:  # neueste zuerst
                if ent["id"] == last_id:
                    break
                newer.append(ent)

            # In zeitlicher Reihenfolge senden
            for ent in reversed(newer):
                if ent["id"] in seen_ids:
                    continue
                if is_relevant_424(ent["title"]):
                    ts_utc = ent["updated_utc"]
                    ts_berlin = ts_utc.astimezone(BERLIN)
                    msg = (
                        "📄 Neue SEC-Meldung (Palatin):\n"
                        f"{ent['title']}\n{ent['link']}\n\n"
                        f"🕒 [UTC]    {ts_utc.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
                        f"🕒 [Berlin] {ts_berlin.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                    )
                    send_telegram(msg)
                    print(f"[Alert] {ent['title']}")
                else:
                    print(
                        f"[Info] Neuer Eintrag, aber nicht 424B3/B5: {ent['title']}"
                    )
                seen_ids.add(ent["id"])
                save_seen_ids(seen_ids)

            # last_id auf neueste ID setzen
            newest_id = entries[0]["id"]
            if newest_id != last_id:
                last_id = newest_id
                save_last_id(last_id)

        except Exception as e:
            print(f"[Loop] Fehler: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    keep_alive()  # wichtig für UptimeRobot
    main_loop()
