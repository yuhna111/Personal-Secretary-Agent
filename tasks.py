"""
Kho công việc.

Đây là vế mà lịch không có. Google Calendar chỉ chứa những gì ĐÃ cố định
giờ. Nó không biết bạn còn 4 tiếng báo cáo chưa viết và hạn là thứ Sáu —
nên nó không bao giờ nói được câu "lịch này bất khả thi".

Một task ở đây gồm: tên, ước tính bao lâu, đã làm được bao nhiêu, hạn chót.
Không tách riêng bảng "commitment" — một task có due_ts CHÍNH LÀ cam kết.
Bớt được một tầng trừu tượng mà không mất gì.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config as cfg

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT NOT NULL,
    est_min    REAL NOT NULL,
    done_min   REAL DEFAULT 0,
    due_ts     INTEGER,
    hard       INTEGER DEFAULT 1,       -- 1 = hạn cứng, 0 = mong muốn
    status     TEXT DEFAULT 'open',     -- open | done | dropped
    created_ts INTEGER,
    source     TEXT                     -- cli | calendar
);
CREATE INDEX IF NOT EXISTS idx_tasks_due ON tasks(due_ts);
"""


def ensure_schema(conn):
    conn.executescript(SCHEMA)


def now_ts():
    return int(datetime.now(timezone.utc).timestamp())


# ------------------------------------------------------------------ ngày giờ
def parse_due(s):
    """
    Nhận nhiều dạng người Việt hay gõ, trả về epoch UTC cuối ngày đó.
      30/8   30/8/2026   2026-08-30   hôm nay   mai
    Trả về None nếu không đọc được.
    """
    if not s:
        return None
    s = s.strip().lower()
    tz = ZoneInfo(cfg.TIMEZONE)
    today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    if s in ("hôm nay", "hom nay", "today"):
        d = today
    elif s in ("mai", "ngày mai", "ngay mai", "tomorrow"):
        d = today + timedelta(days=1)
    elif s in ("mốt", "mot", "ngày mốt", "ngay mot"):
        d = today + timedelta(days=2)
    else:
        d = None
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m", "%d-%m-%Y", "%d-%m"):
            try:
                p = datetime.strptime(s, fmt)
                if "%Y" not in fmt:
                    p = p.replace(year=today.year)
                    # gõ "30/8" vào tháng 12 thì gần như chắc là năm sau
                    cand = p.replace(tzinfo=tz)
                    if (cand - today).days < -60:
                        p = p.replace(year=today.year + 1)
                d = p.replace(tzinfo=tz)
                break
            except ValueError:
                continue
        if d is None:
            return None

    # Hạn chót tính là cuối ngày hôm đó
    end = d.replace(hour=23, minute=59, second=0)
    return int(end.astimezone(timezone.utc).timestamp())


def parse_est(s):
    """240  |  4h  |  90m  |  1h30 -> số phút (float). None nếu sai."""
    if s is None:
        return None
    s = str(s).strip().lower().replace(" ", "")
    if not s:
        return None
    try:
        if s.endswith("m"):
            return float(s[:-1])
        if "h" in s:
            h, _, m = s.partition("h")
            return float(h) * 60 + (float(m) if m else 0)
        return float(s)
    except ValueError:
        return None


def fmt_due(ts):
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts, ZoneInfo(cfg.TIMEZONE)).strftime("%d/%m")


def fmt_min(m):
    h, mm = divmod(int(round(m)), 60)
    return f"{h}h{mm:02d}" if h else f"{mm}p"


# ---------------------------------------------------------------------- CRUD
def add(conn, title, est_min, due_ts=None, hard=True, source="cli"):
    cur = conn.execute(
        "INSERT INTO tasks (title, est_min, due_ts, hard, created_ts, source) "
        "VALUES (?,?,?,?,?,?)",
        (title, est_min, due_ts, int(hard), now_ts(), source),
    )
    conn.commit()
    return cur.lastrowid


def open_tasks(conn):
    """Sắp theo hạn chót (EDF). Task không hạn xếp cuối."""
    return conn.execute(
        "SELECT * FROM tasks WHERE status='open' "
        "ORDER BY CASE WHEN due_ts IS NULL THEN 1 ELSE 0 END, due_ts, id"
    ).fetchall()


def resolve(conn, n):
    """
    Số thứ tự HIỂN THỊ -> id thật trong database.

    Người dùng thấy 1,2,3 liền mạch; bên trong id gốc giữ nguyên vì
    action_log và extendedProperties.task_id trên Google Calendar đều
    tham chiếu tới nó. Đánh số lại id thật sẽ làm các liên kết đó trỏ sai.

    Trả về None nếu số nằm ngoài phạm vi.
    """
    rows = open_tasks(conn)
    if 1 <= n <= len(rows):
        return rows[n - 1]["id"]
    return None


def display_no(conn, task_id):
    """Chiều ngược lại: id thật -> số hiển thị. None nếu việc đã đóng."""
    for i, r in enumerate(open_tasks(conn), 1):
        if r["id"] == task_id:
            return i
    return None


def get(conn, task_id):
    return conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()


def remaining(row):
    return max(0.0, float(row["est_min"]) - float(row["done_min"] or 0))


def log_progress(conn, task_id, minutes):
    """
    Ghi nhận thời gian đã làm. KHÔNG tự đóng việc.

    Bản đầu tiên tự đóng khi done_min chạm est_min. Nghe hợp lý, nhưng nó
    khiến done_min KHÔNG BAO GIỜ vượt quá est_min — nên tỉ lệ thực tế /
    ước tính bị chặn cứng ở 1.0.

    Mà phần vượt quá chính là thứ duy nhất đáng đo. Ước tính 2 tiếng mất
    3 tiếng là thông tin; ước tính 2 tiếng mất đúng 2 tiếng vì hệ thống
    ngừng đếm ở mốc 2 tiếng thì không phải thông tin, đó là hiện vật.

    Giờ chỉ có bạn đóng việc, bằng lệnh `done`.
    """
    conn.execute(
        "UPDATE tasks SET done_min = COALESCE(done_min,0) + ? WHERE id=?",
        (minutes, task_id),
    )
    conn.commit()


def over_estimate(row):
    """Đã vượt ước tính bao nhiêu phút (âm nếu chưa tới)."""
    return float(row["done_min"] or 0) - float(row["est_min"])


def mark_done(conn, task_id):
    conn.execute("UPDATE tasks SET status='done' WHERE id=?", (task_id,))
    conn.commit()


def drop(conn, task_id):
    conn.execute("UPDATE tasks SET status='dropped' WHERE id=?", (task_id,))
    conn.commit()


def exists_similar(conn, title, due_ts):
    """
    Tìm việc đang mở có vẻ trùng với việc sắp thêm.

    So tên không phân biệt hoa thường và bỏ khoảng trắng thừa. Hạn chót
    so theo NGÀY chứ không theo giây — "7/9" gõ hai lần cách nhau vài
    tiếng vẫn ra cùng một ngày nhưng khác timestamp.
    """
    key = " ".join((title or "").lower().split())
    day = None if due_ts is None else due_ts // 86400

    for r in open_tasks(conn):
        if " ".join((r["title"] or "").lower().split()) != key:
            continue
        rday = None if r["due_ts"] is None else r["due_ts"] // 86400
        if rday == day:
            return r
    return None