import os, time, requests, sqlite3, traceback
from delay_catcher_tmx import main as run_delay_catcher  # Original main handler
from threading import Timer, Lock

DEBOUNCE_SEC = float(os.getenv("DEBOUNCE_SEC", "1.5"))  # Can be overridden by .env, default is 1.5 seconds.
_fire_timer = None   # Global timer
_fire_lock = Lock()  # Lock to protect the timer

ASANA_TOKEN  = os.getenv("ASANA_TOKEN")
PROJECT_GID  = os.getenv("ASANA_TMX_PROJECT_ID")
DB_PATH      = os.getenv("EVENTS_DB_PATH", "asana_events.db")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT_SEC", "30"))  # Long polling wait time (seconds)
VERBOSE      = os.getenv("LOG_VERBOSE", "0") == "1"

HEADERS = {"Authorization": f"Bearer {ASANA_TOKEN}"}

def db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT)")
    return conn

def get_sync(conn):
    cur = conn.execute("SELECT v FROM kv WHERE k='sync'")
    row = cur.fetchone()
    return row[0] if row else None

def set_sync(conn, token):
    if token is None:
        conn.execute("DELETE FROM kv WHERE k='sync'")
    else:
        conn.execute("INSERT OR REPLACE INTO kv(k,v) VALUES('sync',?)", (token,))
    conn.commit()

def fetch_events(conn, sync_token=None):
    url = "https://app.asana.com/api/1.0/events"
    params = {"resource": PROJECT_GID, "timeout": POLL_TIMEOUT}
    if sync_token:
        params["sync"] = sync_token

    r = requests.get(url, headers=HEADERS, params=params, timeout=POLL_TIMEOUT + 10)

    # On first run/expiration, a 412 response will include a new sync token in the response body.
    if r.status_code == 412:
        try:
            payload = r.json()
            new_sync = payload.get("sync")
            if new_sync:
                set_sync(conn, new_sync)   # Save it
                return [], new_sync, None  # No events is normal, just get the token
        except Exception:
            pass
        # If not obtained (should not happen), request a reset
        return [], None, "RESET"

    r.raise_for_status()
    payload = r.json()
    events = payload.get("data", [])
    new_sync = payload.get("sync", sync_token)
    return events, new_sync, None

def is_relevant(ev):
    """
    Only handle changes to due_on/due_at or the Delay Reason custom field.
    Exclude Delay Count (number field) to avoid self-triggering.
    """
    ch = (ev.get("change") or {})
    field = ch.get("field")
    if field in ("due_on", "due_at"):
        return True

    if field == "custom_fields":
        target_reason_gid = os.getenv("DELAY_REASON_FIELD_GID") 
        delay_count_gid   = os.getenv("DELAY_COUNT_FIELD_GID")   # Exclude this - or it will be trigger when increment
        newv = (ch.get("new_value") or {})
        gid  = newv.get("gid")
        if delay_count_gid and gid == delay_count_gid:
            return False
        if (not target_reason_gid) or gid == target_reason_gid:
            return True
    return False

def _do_run():
    """When the debounce timer expires, execute the main process."""
    try:
        print("⏱️ Debounce elapsed, executing delay_catcher_tmx…")
        run_delay_catcher()
        print("✅ delay_catcher_tmx executed (debounced)")
    except Exception as e:
        print("❌ Error in debounced run:", e)

def schedule_run():
    """Execute after DEBOUNCE_SEC; if another event occurs during this period, reset the timer."""
    global _fire_timer
    with _fire_lock:
        if _fire_timer:
            _fire_timer.cancel()   # Cancel the previous scheduled task first
        _fire_timer = Timer(DEBOUNCE_SEC, _do_run)
        _fire_timer.daemon = True  # Don't block program exit
        _fire_timer.start()

def main():
    if not ASANA_TOKEN or not PROJECT_GID:
        raise RuntimeError("ASANA_TOKEN / ASANA_TMX_PROJECT_ID not set")

    conn = db()
    sync_token = get_sync(conn)
    print(f"🛰️  Events poller started (project={PROJECT_GID}, timeout={POLL_TIMEOUT}s)")

    while True:
        try:
            events, new_sync, flag = fetch_events(conn, sync_token)
            if new_sync and new_sync != sync_token:
                set_sync(conn, new_sync)   # Write back to DB
                sync_token = new_sync      # Update token in memory

            if flag == "RESET":
                print("⚠️  Sync token reset by server. Restarting stream…")
                sync_token = None
                set_sync(conn, None)
                time.sleep(2)
                continue

            # Initially gets the initial sync (no events), then returns events afterwards
            if new_sync != sync_token:
                set_sync(conn, new_sync)
                sync_token = new_sync

            if VERBOSE and events:
                print(f"📦 Raw events: {events}")

            picked = [e for e in events if is_relevant(e)]
            if picked:
                gids  = [e.get("resource", {}).get("gid") for e in picked]
                kinds = [(e.get("change") or {}).get("field") for e in picked]
                print(f"🎯 Relevant events -> tasks: {gids} fields: {kinds}")
                # Switch to scheduled execution (debounce) to batch a burst of consecutive changes
                schedule_run()
        except requests.RequestException as e:
            print("🌧️ Network/API error:", e)
            time.sleep(2)
        except Exception as e:
            print("❌ Poller crash:", e)
            traceback.print_exc()
            time.sleep(2)

if __name__ == "__main__":
    main()

