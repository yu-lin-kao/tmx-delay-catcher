#!/usr/bin/env python3
import os, time, requests, sqlite3, traceback
from delay_catcher_tmx import main as run_delay_catcher  # 你原來的主處理

ASANA_TOKEN  = os.getenv("ASANA_TOKEN")
PROJECT_GID  = os.getenv("ASANA_TMX_PROJECT_ID")
DB_PATH      = os.getenv("EVENTS_DB_PATH", "asana_events.db")
POLL_TIMEOUT = int(os.getenv("POLL_TIMEOUT_SEC", "30"))  # 長輪詢等待秒數（秒）
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
    """
    參考 Asana Events API：第一次沒有 sync 會取得初始 token；
    之後用 sync 進行長輪詢。412 代表 token 過期，需要重置。
    """
    url = "https://app.asana.com/api/1.0/events"
    params = {"resource": PROJECT_GID, "timeout": POLL_TIMEOUT}
    if sync_token:
        params["sync"] = sync_token
    r = requests.get(url, headers=HEADERS, params=params, timeout=POLL_TIMEOUT + 10)

    if r.status_code == 412:
        return [], None, "RESET"

    r.raise_for_status()
    payload = r.json()
    events = payload.get("data", [])
    new_sync = payload.get("sync", sync_token)
    return events, new_sync, None

def is_relevant(ev):
    """
    只處理 due_on/due_at 變更，或 Delay Reason 自訂欄位變更。
    排除 Delay Count（數字欄位）避免自觸發。
    """
    ch = (ev.get("change") or {})
    field = ch.get("field")
    if field in ("due_on", "due_at"):
        return True

    if field == "custom_fields":
        target_reason_gid = os.getenv("DELAY_REASON_FIELD_GID")  # 建議設定
        delay_count_gid   = os.getenv("DELAY_COUNT_FIELD_GID")   # 必填以排除
        newv = (ch.get("new_value") or {})
        gid  = newv.get("gid")
        if delay_count_gid and gid == delay_count_gid:
            return False
        if (not target_reason_gid) or gid == target_reason_gid:
            return True
    return False

def main():
    if not ASANA_TOKEN or not PROJECT_GID:
        raise RuntimeError("ASANA_TOKEN / ASANA_TMX_PROJECT_ID 未設定")

    conn = db()
    sync_token = get_sync(conn)
    print(f"🛰️  Events poller started (project={PROJECT_GID}, timeout={POLL_TIMEOUT}s)")

    while True:
        try:
            events, new_sync, flag = fetch_events(conn, sync_token)
            if flag == "RESET":
                print("⚠️  Sync token reset by server. Restarting stream…")
                sync_token = None
                set_sync(conn, None)
                time.sleep(2)
                continue

            # 初次會拿到初始 sync（沒有事件），之後才會回事件
            if new_sync != sync_token:
                set_sync(conn, new_sync)
                sync_token = new_sync

            if VERBOSE and events:
                print(f"📦 Raw events: {events}")

            picked = [e for e in events if is_relevant(e)]
            if picked:
                gids = [e.get("resource", {}).get("gid") for e in picked]
                kinds = [ (e.get('change') or {}).get('field') for e in picked ]
                print(f"🎯 Relevant events -> tasks: {gids} fields: {kinds}")
                # 觸發你的主流程（建議在主流程內打印：task 名稱、old/new due、Delay Count +1 等）
                run_delay_catcher()
                print("✅ delay_catcher_tmx executed after events")
        except requests.RequestException as e:
            print("🌧️ Network/API error:", e)
            time.sleep(2)
        except Exception as e:
            print("❌ Poller crash:", e)
            traceback.print_exc()
            time.sleep(2)

if __name__ == "__main__":
    main()

