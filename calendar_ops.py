"""
Lớp ghi. Đây là chỗ DUY NHẤT trong dự án được phép gọi API ghi.

Bốn cầu dao, xếp theo thứ tự kiểm tra:

  1. can_write()     scope hiện tại có cho phép ghi không
  2. SHADOW_MODE     chỉ ghi log, không thực sự gọi API
  3. QUIET_HOURS     không hành động ban đêm
  4. MAX_WRITES      trần thao tác mỗi ngày, chống vòng lặp hỏng

Chế độ hỏng của agent tự chủ không phải là nó ngu, mà là nó làm sai lúc
bạn đang ngủ. Một lần agent tự huỷ buổi họp quan trọng là bạn tắt nó
vĩnh viễn. Bốn cầu dao trên đắt hơn nhiều so với giá trị chúng bảo vệ.

Mọi thao tác đều ghi action_log kèm thông tin hoàn tác TRƯỚC khi thực thi.
"""

import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import auth
import config as cfg
import store


class Blocked(Exception):
    """Thao tác bị một trong các cầu dao chặn lại."""


def _now_local():
    return datetime.now(ZoneInfo(cfg.TIMEZONE))


def _day_start_ts():
    d = _now_local().replace(hour=0, minute=0, second=0, microsecond=0)
    return int(d.astimezone(timezone.utc).timestamp())


def _in_quiet_hours():
    lo, hi = cfg.QUIET_HOURS
    h = _now_local().hour
    return h >= lo or h < hi if lo > hi else lo <= h < hi


def _new_rev():
    return uuid.uuid4().hex[:12]


def _tag(rev, extra=None):
    priv = {cfg.AGENT_TAG: cfg.AGENT_VERSION, "rev": rev}
    if extra:
        priv.update({k: str(v) for k, v in extra.items()})
    return {"private": priv}


def _preflight(conn, op):
    if not auth.can_write():
        raise Blocked(
            f"scope hiện tại chỉ đọc ({cfg.SCOPES[0].rsplit('/', 1)[-1]}). "
            "Đổi SCOPES sang calendar.events nếu thật sự muốn ghi."
        )
    if _in_quiet_hours():
        raise Blocked(f"đang trong giờ yên tĩnh {cfg.QUIET_HOURS}")
    n = store.writes_today(conn, _day_start_ts())
    if n >= cfg.MAX_WRITES_PER_DAY:
        raise Blocked(f"đã chạm trần {cfg.MAX_WRITES_PER_DAY} thao tác/ngày")


def _record(conn, op, event_id, reason, executed, undo=None, payload=None):
    store.log_action(conn, op, event_id, reason, executed, undo, payload)
    conn.commit()


# ------------------------------------------------------------------ thao tác
def create_block(service, conn, summary, start_iso, end_iso, reason,
                 meta=None, dry_run=None):
    """
    Tạo một block trên lịch, có gắn nhãn agent.

    meta đi vào extendedProperties.private -> state của agent nằm ngay
    trên sự kiện. Bạn kéo thả block trong app Calendar, agent đọc lại
    vẫn biết block đó thuộc task nào. Không cần đồng bộ hai chiều giữa
    DB và lịch.
    """
    shadow = cfg.SHADOW_MODE if dry_run is None else dry_run
    rev = _new_rev()
    body = {
        "summary": summary,
        "start": {"dateTime": start_iso, "timeZone": cfg.TIMEZONE},
        "end": {"dateTime": end_iso, "timeZone": cfg.TIMEZONE},
        "extendedProperties": _tag(rev, meta),
        "description": f"[agent] {reason}",
    }

    if shadow:
        _record(conn, "insert", None, reason, executed=False, payload=body)
        return {"shadow": True, "body": body}

    _preflight(conn, "insert")
    ev = service.events().insert(calendarId=cfg.CALENDAR_ID, body=body).execute()
    store.set_state(conn, f"rev:{ev['id']}", rev)
    _record(conn, "insert", ev["id"], reason, executed=True,
            undo={"op": "delete", "event_id": ev["id"]}, payload=body)
    return ev


def move_block(service, conn, event_id, start_iso, end_iso, reason, dry_run=None):
    """Dời một block. Chỉ cho phép dời block do chính agent tạo."""
    shadow = cfg.SHADOW_MODE if dry_run is None else dry_run

    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        raise Blocked(f"không có sự kiện {event_id} trong bản sao cục bộ")
    if not row["is_agent"]:
        raise Blocked(
            "sự kiện này không do agent tạo. Dời sự kiện của bạn hoặc của "
            "người khác là thao tác không hoàn tác được -> phải hỏi trước."
        )

    rev = _new_rev()
    body = {
        "start": {"dateTime": start_iso, "timeZone": cfg.TIMEZONE},
        "end": {"dateTime": end_iso, "timeZone": cfg.TIMEZONE},
        "extendedProperties": _tag(rev),
    }
    undo = {"op": "patch", "event_id": event_id,
            "start_ts": row["start_ts"], "end_ts": row["end_ts"]}

    if shadow:
        _record(conn, "patch", event_id, reason, executed=False,
                undo=undo, payload=body)
        return {"shadow": True, "body": body}

    _preflight(conn, "patch")
    ev = service.events().patch(
        calendarId=cfg.CALENDAR_ID, eventId=event_id, body=body
    ).execute()
    store.set_state(conn, f"rev:{event_id}", rev)
    _record(conn, "patch", event_id, reason, executed=True, undo=undo, payload=body)
    return ev


def remove_block(service, conn, event_id, reason, dry_run=None):
    """Xoá block do agent tạo. Không bao giờ xoá sự kiện của người dùng."""
    shadow = cfg.SHADOW_MODE if dry_run is None else dry_run

    row = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if row is None:
        raise Blocked(f"không có sự kiện {event_id} trong bản sao cục bộ")
    if not row["is_agent"]:
        raise Blocked("từ chối xoá sự kiện không do agent tạo")

    undo = {"op": "insert", "raw": row["raw"]}

    if shadow:
        _record(conn, "delete", event_id, reason, executed=False, undo=undo)
        return {"shadow": True}

    _preflight(conn, "delete")
    service.events().delete(
        calendarId=cfg.CALENDAR_ID, eventId=event_id
    ).execute()
    _record(conn, "delete", event_id, reason, executed=True, undo=undo)
    return {"deleted": event_id}
