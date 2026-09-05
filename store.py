"""
Lớp lưu trữ.

Ba bảng, mỗi bảng một vai trò rõ ràng:

  events      Bản sao cục bộ của lịch. Agent suy luận trên bảng này,
              không gọi API mỗi lần cần biết lịch trông ra sao.

  sync_state  syncToken. Đây là thứ khiến "thời gian thực" trở nên rẻ:
              Google chỉ trả về những gì đã đổi từ lần gọi trước.

  action_log  MỌI thứ agent đã làm hoặc định làm, kèm thông tin hoàn tác.
              Đây là bảng quan trọng nhất về mặt an toàn. Nếu agent làm
              bậy, đây là chỗ bạn nhìn để biết nó đã làm gì và gỡ ra sao.
"""

import json
import sqlite3
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id          TEXT PRIMARY KEY,
    summary     TEXT,
    start_ts    INTEGER,          -- unix epoch UTC, NULL nếu là sự kiện cả ngày
    end_ts      INTEGER,
    all_day     INTEGER DEFAULT 0,
    status      TEXT,             -- confirmed | tentative | cancelled
    is_agent    INTEGER DEFAULT 0,
    agent_rev   TEXT,
    updated     TEXT,
    raw         TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ts);

CREATE TABLE IF NOT EXISTS sync_state (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS action_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    ts          INTEGER NOT NULL,
    op          TEXT NOT NULL,     -- insert | patch | delete
    event_id    TEXT,
    reason      TEXT,
    executed    INTEGER DEFAULT 0, -- 0 = shadow mode, chỉ ghi log
    undo        TEXT,              -- JSON đủ để hoàn tác
    payload     TEXT,
    undone      INTEGER DEFAULT 0  -- 1 = đã được hoàn tác
);
CREATE INDEX IF NOT EXISTS idx_log_ts ON action_log(ts);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    import tasks
    conn.executescript(tasks.SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn):
    """
    Thêm cột mới vào database đã tồn tại.

    CREATE TABLE IF NOT EXISTS không đụng tới bảng đã có, nên người dùng
    nâng cấp từ bản cũ sẽ thiếu cột và mọi truy vấn liên quan đều hỏng.
    Kiểm tra rồi thêm là cách rẻ nhất, không cần công cụ migration.
    """
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(action_log)")}
    if "undone" not in cols:
        conn.execute("ALTER TABLE action_log ADD COLUMN undone INTEGER DEFAULT 0")
        conn.commit()


def now_ts():
    return int(datetime.now(timezone.utc).timestamp())


# ------------------------------------------------------------------ sync_state
def get_state(conn, key, default=None):
    r = conn.execute("SELECT value FROM sync_state WHERE key=?", (key,)).fetchone()
    return r["value"] if r else default


def set_state(conn, key, value):
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?,?)",
        (key, value),
    )


# ---------------------------------------------------------------------- events
def upsert_event(conn, ev):
    conn.execute(
        "INSERT OR REPLACE INTO events "
        "(id, summary, start_ts, end_ts, all_day, status, is_agent, agent_rev, updated, raw) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (ev["id"], ev.get("summary"), ev.get("start_ts"), ev.get("end_ts"),
         int(ev.get("all_day", 0)), ev.get("status"), int(ev.get("is_agent", 0)),
         ev.get("agent_rev"), ev.get("updated"),
         json.dumps(ev.get("raw", {}), ensure_ascii=False)),
    )


def delete_event(conn, event_id):
    conn.execute("DELETE FROM events WHERE id=?", (event_id,))


def events_between(conn, lo_ts, hi_ts):
    return conn.execute(
        "SELECT * FROM events WHERE status!='cancelled' "
        "AND start_ts IS NOT NULL AND start_ts < ? AND end_ts > ? "
        "ORDER BY start_ts",
        (hi_ts, lo_ts),
    ).fetchall()


def count_events(conn):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM events WHERE status!='cancelled'"
    ).fetchone()["c"]


# ------------------------------------------------------------------ action_log
def log_action(conn, op, event_id, reason, executed, undo=None, payload=None):
    cur = conn.execute(
        "INSERT INTO action_log (ts, op, event_id, reason, executed, undo, payload) "
        "VALUES (?,?,?,?,?,?,?)",
        (now_ts(), op, event_id, reason, int(executed),
         json.dumps(undo, ensure_ascii=False) if undo else None,
         json.dumps(payload, ensure_ascii=False) if payload else None),
    )
    return cur.lastrowid


def writes_today(conn, day_start_ts):
    return conn.execute(
        "SELECT COUNT(*) AS c FROM action_log WHERE executed=1 AND ts>=?",
        (day_start_ts,),
    ).fetchone()["c"]


def recent_actions(conn, limit=20):
    return conn.execute(
        "SELECT * FROM action_log ORDER BY ts DESC LIMIT ?", (limit,)
    ).fetchall()


def undoable_actions(conn, limit=20):
    """Các hành động ĐÃ THỰC HIỆN THẬT và chưa bị hoàn tác."""
    return conn.execute(
        "SELECT * FROM action_log WHERE executed=1 AND COALESCE(undone,0)=0 "
        "AND undo IS NOT NULL ORDER BY ts DESC LIMIT ?",
        (limit,),
    ).fetchall()


def mark_undone(conn, action_id):
    conn.execute("UPDATE action_log SET undone=1 WHERE id=?", (action_id,))
    conn.commit()