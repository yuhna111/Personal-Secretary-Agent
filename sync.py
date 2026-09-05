"""
Đồng bộ tăng dần bằng syncToken.

Đây là thứ thay thế push notification. Google Calendar có webhook thật,
nhưng nó đòi domain đã xác minh, HTTPS hợp lệ, và channel hết hạn sau vài
ngày nên phải có job gia hạn — bốn bộ phận phải bảo trì, đổi lấy một tín
hiệu "có gì đó đã đổi" mà bạn vẫn phải gọi API để biết đổi cái gì.

syncToken cho kết quả tương đương với một phần công sức: gọi events.list
kèm token, Google chỉ trả về phần đã thay đổi. Không đổi gì thì trả rỗng,
gần như miễn phí. Poll 90 giây là đủ "thời gian thực" cho một thư ký.

Hệ quả kiến trúc quan trọng: không cần webhook nghĩa là không cần IP công
khai. Chạy được trên máy ở nhà, Raspberry Pi, hay cron của GitHub Actions.
"""

from datetime import datetime, timedelta, timezone

import config as cfg
import store


# ------------------------------------------------------------------ chuẩn hoá
def _parse_dt(node):
    """Trả về (epoch_utc, is_all_day). node là ev['start'] hoặc ev['end']."""
    if not node:
        return None, False
    if "dateTime" in node:
        s = node["dateTime"]
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return int(datetime.fromisoformat(s).timestamp()), False
    if "date" in node:
        d = datetime.fromisoformat(node["date"]).replace(tzinfo=timezone.utc)
        return int(d.timestamp()), True
    return None, False


def normalize(ev):
    start_ts, ad1 = _parse_dt(ev.get("start"))
    end_ts, ad2 = _parse_dt(ev.get("end"))
    priv = (ev.get("extendedProperties") or {}).get("private") or {}
    return {
        "id": ev["id"],
        "summary": ev.get("summary"),
        "start_ts": start_ts,
        "end_ts": end_ts,
        "all_day": ad1 or ad2,
        "status": ev.get("status"),
        "is_agent": priv.get(cfg.AGENT_TAG) == cfg.AGENT_VERSION,
        "agent_rev": priv.get("rev"),
        "updated": ev.get("updated"),
        "raw": ev,
    }


# --------------------------------------------------------------------- sync
def _window():
    now = datetime.now(timezone.utc)
    return (
        (now - timedelta(days=cfg.SYNC_PAST_DAYS)).isoformat().replace("+00:00", "Z"),
        (now + timedelta(days=cfg.SYNC_FUTURE_DAYS)).isoformat().replace("+00:00", "Z"),
    )


def _list_page(service, params):
    return service.events().list(**params).execute()


def run_sync(service, conn, verbose=True):
    """
    Trả về dict thống kê. Tự xử lý trường hợp syncToken hết hạn (HTTP 410)
    bằng cách làm lại full sync — đây là chuyện bình thường, không phải lỗi.
    """
    token = store.get_state(conn, "sync_token")
    full = token is None

    params = {"calendarId": cfg.CALENDAR_ID, "singleEvents": True,
              "maxResults": 250, "showDeleted": True}
    if full:
        lo, hi = _window()
        params.update({"timeMin": lo, "timeMax": hi, "orderBy": "startTime"})
        if verbose:
            print(f"[sync] full sync: {lo[:10]} .. {hi[:10]}")
    else:
        params["syncToken"] = token

    n_upd = n_del = n_self = 0
    page_token = None
    next_sync_token = None

    while True:
        if page_token:
            params["pageToken"] = page_token
        else:
            params.pop("pageToken", None)

        try:
            resp = _list_page(service, params)
        except Exception as exc:
            if _is_gone(exc):
                # syncToken hết hạn. Xoá và làm lại từ đầu.
                if verbose:
                    print("[sync] syncToken hết hạn (410), làm lại full sync")
                store.set_state(conn, "sync_token", None)
                conn.commit()
                return run_sync(service, conn, verbose)
            raise

        for ev in resp.get("items", []):
            n = normalize(ev)
            if n["status"] == "cancelled":
                store.delete_event(conn, n["id"])
                n_del += 1
                continue
            if n["is_agent"] and _is_own_write(conn, n):
                # Thay đổi do chính agent vừa gây ra. Vẫn lưu vào bản sao,
                # nhưng KHÔNG tính là "có gì đó đã đổi" -> không kích hoạt
                # planner. Không có bước này, agent phản ứng với chính nó
                # và bạn được một vòng lặp ghi vào lịch thật lúc 3h sáng.
                store.upsert_event(conn, n)
                n_self += 1
                continue
            store.upsert_event(conn, n)
            n_upd += 1

        page_token = resp.get("nextPageToken")
        if not page_token:
            next_sync_token = resp.get("nextSyncToken")
            break

    if next_sync_token:
        store.set_state(conn, "sync_token", next_sync_token)
    store.set_state(conn, "last_sync_ts", str(store.now_ts()))
    conn.commit()

    stats = {"full": full, "updated": n_upd, "deleted": n_del,
             "self": n_self, "changed": n_upd + n_del}
    if verbose and (stats["changed"] or full):
        print(f"[sync] {n_upd} cập nhật, {n_del} xoá, {n_self} tự-ghi (bỏ qua)")
    return stats


def _is_gone(exc):
    return getattr(getattr(exc, "resp", None), "status", None) == 410 \
        or "410" in str(exc)


def _is_own_write(conn, n):
    """
    Sự kiện mang nhãn agent, và rev khớp với rev agent vừa ghi
    -> đây là tiếng vọng của chính mình.
    """
    last = store.get_state(conn, f"rev:{n['id']}")
    return last is not None and last == n["agent_rev"]
