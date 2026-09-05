"""
Đường nhập việc thứ hai: qua chính Google Calendar.

Bạn đang trên xe buýt, nhớ ra việc phải làm. Mở app Calendar, tạo sự kiện
đặt tên:

    @task Viết báo cáo thực tập | 240 | 30/8
    @task Ôn Giải tích | 3h | mai
    @task Đọc tài liệu | 90m

Agent đang sync sẵn, thấy tiền tố @task thì hiểu đây là LỆNH chứ không
phải lịch hẹn, nạp vào kho công việc rồi đánh dấu sự kiện là đã xử lý.

Cách này gọn ở chỗ: kênh lệnh và kênh dữ liệu là một, nên không bao giờ
lệch pha. Không thêm scope, không thêm dịch vụ, không thêm app.
"""

import config as cfg
import tasks as T


def parse_task_line(summary):
    """
    '@task Tiêu đề | 240 | 30/8' -> dict(title, est_min, due_ts)
    Trả về None nếu không phải lệnh task.
    Thiếu ước tính thì mặc định 60 phút — thà đoán còn hơn bỏ qua.
    """
    if not summary:
        return None
    s = summary.strip()
    if not s.lower().startswith(cfg.TASK_PREFIX.lower()):
        return None

    body = s[len(cfg.TASK_PREFIX):].strip()
    if not body:
        return None

    parts = [p.strip() for p in body.split("|")]
    title = parts[0]
    if not title:
        return None

    est = T.parse_est(parts[1]) if len(parts) > 1 else None
    due = T.parse_due(parts[2]) if len(parts) > 2 else None

    return {"title": title, "est_min": est or 60.0, "due_ts": due,
            "est_missing": est is None}


def scan(conn):
    """
    Quét bản sao lịch cục bộ tìm các sự kiện @task chưa xử lý.
    Trả về list dict(event_id, parsed, duplicate).
    """
    rows = conn.execute(
        "SELECT id, summary FROM events WHERE status!='cancelled' "
        "AND summary LIKE ?",
        (cfg.TASK_PREFIX + "%",),
    ).fetchall()

    found = []
    for r in rows:
        if store_processed(conn, r["id"]):
            continue
        p = parse_task_line(r["summary"])
        if not p:
            continue
        dup = T.exists_similar(conn, p["title"], p["due_ts"]) is not None
        found.append({"event_id": r["id"], "parsed": p, "duplicate": dup})
    return found


def store_processed(conn, event_id):
    import store
    return store.get_state(conn, f"inbox:{event_id}") is not None


def mark_processed(conn, event_id, task_id):
    import store
    store.set_state(conn, f"inbox:{event_id}", str(task_id))
    conn.commit()


def ingest(conn, service=None, cleanup=None):
    """
    Nạp các lệnh @task vào kho công việc.

    cleanup=True thì xoá sự kiện lệnh khỏi lịch sau khi nạp. Mặc định
    theo SHADOW_MODE — đang shadow thì không đụng gì vào lịch thật.
    """
    if cleanup is None:
        cleanup = not cfg.SHADOW_MODE

    results = []
    for item in scan(conn):
        p = item["parsed"]
        if item["duplicate"]:
            mark_processed(conn, item["event_id"], -1)
            results.append({**item, "action": "trùng, bỏ qua"})
            continue

        tid = T.add(conn, p["title"], p["est_min"], p["due_ts"], source="calendar")
        mark_processed(conn, item["event_id"], tid)
        action = "đã nạp"

        if cleanup and service is not None:
            try:
                service.events().delete(
                    calendarId=cfg.CALENDAR_ID, eventId=item["event_id"]
                ).execute()
                action += ", đã xoá sự kiện lệnh"
            except Exception as exc:
                action += f", không xoá được ({exc})"

        results.append({**item, "action": action, "task_id": tid})

    return results
