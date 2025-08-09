#!/usr/bin/env python3
import os, time, requests, sqlite3, traceback
from delay_catcher_tmx import main as run_delay_catcher  # 你原來的主處理
from threading import Timer, Lock

DEBOUNCE_SEC = float(os.getenv("DEBOUNCE_SEC", "1.5"))  # 可用 .env 覆寫，預設 1.5 秒
_fire_timer = None   # 全域計時器
_fire_lock = Lock()  # 保護計時器的鎖

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
    url = "https://app.asana.com/api/1.0/events"
    params = {"resource": PROJECT_GID, "timeout": POLL_TIMEOUT}
    if sync_token:
        params["sync"] = sync_token

    r = requests.get(url, headers=HEADERS, params=params, timeout=POLL_TIMEOUT + 10)

    # ✅ 關鍵修正：第一次/過期時 412，回應 body 會附上新的 sync token
    if r.status_code == 412:
        try:
            payload = r.json()
            new_sync = payload.get("sync")
            if new_sync:
                set_sync(conn, new_sync)   # 存起來
                return [], new_sync, None  # 沒事件很正常，拿到 token 即可
        except Exception:
            pass
        # 萬一沒有拿到（理論上不會），再要求重置
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

def _do_run():
    """Debounce 計時到時，真的執行你的主流程。"""
    try:
        print("⏱️ Debounce elapsed, executing delay_catcher_tmx…")
        run_delay_catcher()
        print("✅ delay_catcher_tmx executed (debounced)")
    except Exception as e:
        print("❌ Error in debounced run:", e)

def schedule_run():
    """在 DEBOUNCE_SEC 後執行；若期間又有事件，重置計時。"""
    global _fire_timer
    with _fire_lock:
        if _fire_timer:
            _fire_timer.cancel()   # 先取消上一個排程
        _fire_timer = Timer(DEBOUNCE_SEC, _do_run)
        _fire_timer.daemon = True  # 不阻擋程式關閉
        _fire_timer.start()

def main():
    if not ASANA_TOKEN or not PROJECT_GID:
        raise RuntimeError("ASANA_TOKEN / ASANA_TMX_PROJECT_ID 未設定")

    conn = db()
    sync_token = get_sync(conn)
    print(f"🛰️  Events poller started (project={PROJECT_GID}, timeout={POLL_TIMEOUT}s)")

    while True:
        try:
            events, new_sync, flag = fetch_events(conn, sync_token)
            if new_sync and new_sync != sync_token:
                set_sync(conn, new_sync)   # 寫回 DB
                sync_token = new_sync      # 更新記憶體中的 token

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
                gids  = [e.get("resource", {}).get("gid") for e in picked]
                kinds = [(e.get("change") or {}).get("field") for e in picked]
                print(f"🎯 Relevant events -> tasks: {gids} fields: {kinds}")
                # ✅ 改成排程執行（debounce），把同一波連續修改合併處理
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

