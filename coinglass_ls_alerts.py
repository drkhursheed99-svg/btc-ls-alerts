#!/usr/bin/env python3
"""
CoinGlass BTC Long/Short % alerts -> WhatsApp and/or Android notification.

Alerts when the BTC long-account % (1h, 4h, 1d) climbs past 51, 52, 53, 54, 55.

Delivery channels (a channel turns on automatically when its setting is present):
  * WhatsApp        -> WA_PHONE + WA_APIKEY   (free CallMeBot service)
  * Android push    -> NTFY_TOPIC             (free ntfy app)
  * Native Android  -> runs inside Termux on the phone (needs Termux:API app)

Modes:
  python coinglass_ls_alerts.py --test    print values + send a test message
  python coinglass_ls_alerts.py --once    check once and exit (for GitHub Actions / cron)
  python coinglass_ls_alerts.py           loop forever (PC, VPS, or Termux on your phone)

All secrets come from environment variables, so no keys are stored in this file.
"""
import json
import os
import shutil
import subprocess
import sys
import time
import requests

# ----------------------------- SETTINGS ------------------------------------
COINGLASS_KEY = os.environ.get("COINGLASS_API_KEY", "")

WA_PHONE = os.environ.get("WA_PHONE", "")        # e.g. +923001234567
WA_APIKEY = os.environ.get("WA_APIKEY", "")      # from CallMeBot
NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")    # e.g. btc-ls-alerts-8f3k2x
NTFY_SERVER = os.environ.get("NTFY_SERVER", "https://ntfy.sh")

EXCHANGE = os.environ.get("LS_EXCHANGE", "Binance")
PAIR = os.environ.get("LS_PAIR", "BTCUSDT")
INTERVALS = ["1h", "4h", "1d"]
LEVELS = [51, 52, 53, 54, 55]
SIDES = os.environ.get("LS_SIDES", "long").split(",")      # "long" or "long,short"
ALERT_ON_DROP = os.environ.get("LS_ALERT_ON_DROP", "0") == "1"

POLL_SECONDS = 300
STATE_FILE = os.environ.get("LS_STATE_FILE", "ls_state.json")
# ---------------------------------------------------------------------------

BASE = "https://open-api-v4.coinglass.com"
FIELD = {"long": "global_account_long_percent", "short": "global_account_short_percent"}


def latest_percent(interval, side):
    r = requests.get(
        BASE + "/api/futures/global-long-short-account-ratio/history",
        headers={"CG-API-KEY": COINGLASS_KEY, "Accept": "application/json"},
        params={"exchange": EXCHANGE, "symbol": PAIR, "interval": interval, "limit": 2},
        timeout=20,
    )
    r.raise_for_status()
    j = r.json()
    if str(j.get("code")) != "0":
        raise RuntimeError(f"CoinGlass error: {j.get('msg')}")
    rows = sorted(j["data"], key=lambda x: x["time"])
    return float(rows[-1][FIELD[side]])


def level_of(value):
    return max([lv for lv in LEVELS if value >= lv], default=0)


# ----------------------------- DELIVERY ------------------------------------
def notify(title, text):
    sent = False
    if WA_PHONE and WA_APIKEY:
        try:
            r = requests.get(
                "https://api.callmebot.com/whatsapp.php",
                params={"phone": WA_PHONE, "text": f"{title}\n{text}", "apikey": WA_APIKEY},
                timeout=30,
            )
            print(f"[whatsapp {r.status_code}]")
            sent = True
        except Exception as e:
            print(f"[whatsapp error] {e}")
    if NTFY_TOPIC:
        try:
            r = requests.post(
                f"{NTFY_SERVER}/{NTFY_TOPIC}",
                data=text.encode("utf-8"),
                headers={"Title": title, "Priority": "high", "Tags": "chart_with_upwards_trend"},
                timeout=15,
            )
            print(f"[ntfy {r.status_code}]")
            sent = True
        except Exception as e:
            print(f"[ntfy error] {e}")
    if shutil.which("termux-notification"):
        try:
            subprocess.run(["termux-notification", "--title", title, "--content", text,
                            "--priority", "high", "--vibrate", "300,200,300"], timeout=15)
            print("[termux notification]")
            sent = True
        except Exception as e:
            print(f"[termux error] {e}")
    if not sent:
        print("[no channel configured] " + title + " - " + text)
    print(f"  -> {title}: {text}")


# ------------------------------- STATE -------------------------------------
def load_state():
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w") as f:
        json.dump(state, f)


def check_all(state):
    for interval in INTERVALS:
        for side in SIDES:
            key = f"{interval}-{side}"
            try:
                value = latest_percent(interval, side)
            except Exception as e:
                print(f"[warn] {key}: {e}")
                continue
            lvl = level_of(value)
            prev = state.get(key)
            title = f"BTC {interval} {side.upper()} %"
            if prev is None:
                print(f"[start] {title}: {value:.2f}% (level {lvl or 'below ' + str(LEVELS[0])})")
            elif lvl > prev:
                notify(title + f" crossed {lvl}%", f"Now {value:.2f}% ({EXCHANGE} {PAIR})")
            elif lvl < prev and ALERT_ON_DROP:
                notify(title + f" fell below {prev}%", f"Now {value:.2f}% ({EXCHANGE} {PAIR})")
            state[key] = lvl
    save_state(state)


def main():
    if not COINGLASS_KEY:
        sys.exit("Set the COINGLASS_API_KEY environment variable first.")
    if "--test" in sys.argv:
        for interval in INTERVALS:
            for side in SIDES:
                try:
                    print(f"BTC {interval} {side}: {latest_percent(interval, side):.2f}%")
                except Exception as e:
                    print(f"BTC {interval} {side}: ERROR {e}")
        notify("CoinGlass alerts connected", "Test message - your BTC long/short alerts work.")
        return
    state = load_state()
    if "--once" in sys.argv:
        check_all(state)
        return
    print(f"Watching BTC {INTERVALS} on {EXCHANGE}, levels {LEVELS}. Ctrl+C to stop.")
    while True:
        check_all(state)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
