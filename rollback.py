"""
Hoàn tác và dọn dẹp — hai thứ bạn CẦN trước khi cho agent ghi thật.

Từ Tầng 1, mỗi hành động ghi đều lưu kèm thông tin đủ để gỡ, nhưng chưa
có lệnh nào dùng tới. Đây là lệnh đó.

Nguyên tắc giữ nguyên từ calendar_ops: agent chỉ đụng vào sự kiện DO
CHÍNH NÓ tạo. Hoàn tác cũng vậy — không bao giờ khôi phục đè lên thứ bạn
đã sửa tay sau đó.
"""

import json

import config as cfg
import store
import tasks as T


def _priv(ev):
    return (ev.get("extendedProperties") or {}).get("private") or {}


# ------------------------------------------------------------------ hoàn tác
def undo_one(service, conn, row, dry_run=False):
    """
    Gỡ một hành động. Trả về (ok, mô_tả).
    """
    if not row["undo"]:
        return False, "không có thông tin hoàn tác"

    info = json.loads(row["undo"])
    op = info.get("op")

    if dry_run:
        return True, f"sẽ {op} {info.get('event_id') or ''}".strip()

    try:
        if op == "delete":
            service.events().delete(
                calendarId=cfg.CALENDAR_ID, eventId=info["event_id"]
            ).execute()
            desc = "đã xoá block agent tạo"

        elif op == "patch":
            body = {
                "start": {"dateTime": _iso(info["start_ts"]),
                          "timeZone": cfg.TIMEZONE},
                "end": {"dateTime": _iso(info["end_ts"]),
                        "timeZone": cfg.TIMEZONE},
            }
            service.events().patch(
                calendarId=cfg.CALENDAR_ID, eventId=info["event_id"], body=body
            ).execute()
            desc = "đã trả block về giờ cũ"

        elif op == "insert":
            raw = json.loads(info["raw"]) if isinstance(info["raw"], str) \
                else info["raw"]
            body = {k: raw[k] for k in
                    ("summary", "start", "end", "description",
                     "extendedProperties") if k in raw}
            service.events().insert(
                calendarId=cfg.CALENDAR_ID, body=body
            ).execute()
            desc = "đã tạo lại block bị xoá"

        else:
            return False, f"không biết cách gỡ thao tác '{op}'"

    except Exception as exc:
        msg = str(exc)
        if "404" in msg or "410" in msg:
            # Sự kiện không còn trên lịch — bạn đã tự xoá tay rồi.
            # Coi như đã hoàn tác xong, đánh dấu để khỏi thử lại mãi.
            store.mark_undone(conn, row["id"])
            return True, "sự kiện không còn trên lịch (bạn đã xoá tay)"
        return False, msg[:120]

    store.mark_undone(conn, row["id"])
    if info.get("event_id"):
        store.delete_event(conn, info["event_id"])
    conn.commit()
    return True, desc


def _iso(ts):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.fromtimestamp(ts, ZoneInfo(cfg.TIMEZONE)).isoformat()


# ------------------------------------------------------------------ dọn dẹp
def find_stale(conn):
    """
    Tìm các block agent đã ghi mà giờ không còn lý do tồn tại:
      - việc đã xong hoặc đã bỏ
      - việc đã bị xoá khỏi kho

    Chỉ xét block TRONG TƯƠNG LAI. Block quá khứ là lịch sử, giữ nguyên.
    """
    now = store.now_ts()
    stale = []

    rows = conn.execute(
        "SELECT * FROM events WHERE is_agent=1 AND status!='cancelled' "
        "AND start_ts > ? ORDER BY start_ts",
        (now,),
    ).fetchall()

    for r in rows:
        raw = json.loads(r["raw"] or "{}")
        tid = _priv(raw).get("task_id")
        if tid is None:
            continue
        try:
            tid = int(tid)
        except (TypeError, ValueError):
            continue

        task = T.get(conn, tid)
        if task is None:
            stale.append((r, f"việc #{tid} không còn trong kho"))
        elif task["status"] != "open":
            stale.append((r, f"việc '{task['title'][:30]}' đã {task['status']}"))

    return stale


def cleanup(service, conn, dry_run=False):
    """Xoá các block không còn lý do tồn tại. Trả về list (tên, lý do, ok)."""
    out = []
    for ev, why in find_stale(conn):
        if dry_run:
            out.append((ev["summary"], why, True))
            continue
        try:
            service.events().delete(
                calendarId=cfg.CALENDAR_ID, eventId=ev["id"]
            ).execute()
            store.delete_event(conn, ev["id"])
            store.log_action(conn, "delete", ev["id"],
                             f"dọn dẹp: {why}", executed=True)
            conn.commit()
            out.append((ev["summary"], why, True))
        except Exception as exc:
            msg = str(exc)
            if "404" in msg or "410" in msg:
                store.delete_event(conn, ev["id"])
                conn.commit()
                out.append((ev["summary"], "đã không còn trên lịch", True))
            else:
                out.append((ev["summary"], msg[:80], False))
    return out