"""
Bộ máy quyết định. KHÔNG có LLM ở đây, và đó là chủ ý.

Ba việc, xếp theo giá trị giảm dần:

  1. Kiểm tra khả thi  <- thứ đáng giá nhất
     "Còn 11 tiếng việc, chỉ còn 7 tiếng trống trước hạn."
     Google Calendar không bao giờ nói câu này. Nó cho bạn nhét 12 việc
     vào 8 tiếng mà không phản đối một tiếng nào.

  2. Tìm chỗ trống
     Trừ ra sự kiện đã có, giờ ngủ, và khoảng đệm hai đầu.

  3. Đề xuất block cụ thể
     Tham lam theo EDF (hạn gần nhất trước). Không tối ưu toàn cục —
     và không cần, vì bạn sẽ sửa tay một nửa số đề xuất.

Toàn bộ đều tất định: cùng đầu vào cho ra cùng đầu ra, test được,
debug được, giải thích được. Đây là lý do LLM không nên ngồi ở tầng này.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config as cfg
import store
import tasks as T


def _tz():
    return ZoneInfo(cfg.TIMEZONE)


def _day_window(day_local):
    """Khung giờ làm việc của một ngày -> (epoch_lo, epoch_hi)."""
    lo_h, hi_h = cfg.WORK_HOURS
    lo = day_local.replace(hour=lo_h, minute=0, second=0, microsecond=0)
    hi = day_local.replace(hour=0, minute=0, second=0, microsecond=0) \
        + timedelta(hours=hi_h)
    return (int(lo.astimezone(timezone.utc).timestamp()),
            int(hi.astimezone(timezone.utc).timestamp()))


def _busy(conn, lo, hi):
    """Các khoảng đã bận trong [lo, hi), đã cộng buffer hai đầu, đã gộp."""
    buf = cfg.BUFFER_MIN * 60
    rows = conn.execute(
        "SELECT start_ts, end_ts FROM events "
        "WHERE status!='cancelled' AND all_day=0 "
        "AND start_ts IS NOT NULL AND end_ts IS NOT NULL "
        "AND start_ts < ? AND end_ts > ? ORDER BY start_ts",
        (hi, lo),
    ).fetchall()

    spans = [(r["start_ts"] - buf, r["end_ts"] + buf) for r in rows]
    if not spans:
        return []

    merged = [list(spans[0])]
    for s, e in spans[1:]:
        if s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


def free_slots(conn, from_ts=None, days=None):
    """
    Trả về list (start_ts, end_ts) các khoảng trống khả dụng.
    Chỉ tính từ thời điểm hiện tại trở đi — quá khứ không xếp được nữa.
    """
    days = days or cfg.HORIZON_DAYS
    now = store.now_ts()
    from_ts = max(from_ts or now, now)

    tz = _tz()
    d0 = datetime.fromtimestamp(from_ts, tz).replace(
        hour=0, minute=0, second=0, microsecond=0)

    out = []
    min_len = cfg.MIN_BLOCK_MIN * 60

    for i in range(days):
        day = d0 + timedelta(days=i)
        lo, hi = _day_window(day)
        lo = max(lo, from_ts)
        if lo >= hi:
            continue

        cursor = lo
        for bs, be in _busy(conn, lo, hi):
            if bs > cursor:
                seg = (cursor, min(bs, hi))
                if seg[1] - seg[0] >= min_len:
                    out.append(seg)
            cursor = max(cursor, be)
            if cursor >= hi:
                break
        if hi - cursor >= min_len:
            out.append((cursor, hi))

    return out


def free_minutes_before(slots, deadline_ts):
    """Tổng số phút trống từ giờ tới deadline."""
    total = 0
    for s, e in slots:
        e = min(e, deadline_ts)
        if e > s:
            total += (e - s) / 60.0
    return total


# ------------------------------------------------------------------ khả thi
def feasibility(conn, days=None):
    """
    Kiểm tra tích luỹ theo EDF.

    Không chỉ hỏi "task này có kịp không" mà hỏi "task này CỘNG với mọi
    task hạn sớm hơn có kịp không". Đây mới là câu đúng: bạn không thể
    làm hai việc cùng lúc, nên việc hạn thứ Sáu phải chờ việc hạn thứ Ba
    xong đã.
    """
    slots = free_slots(conn, days=days)
    rows = T.open_tasks(conn)

    total_free = sum((e - s) for s, e in slots) / 60.0
    total_work = sum(T.remaining(r) for r in rows)

    problems = []
    cumulative = 0.0
    for r in rows:
        cumulative += T.remaining(r)
        if r["due_ts"] is None:
            continue
        avail = free_minutes_before(slots, r["due_ts"])
        if cumulative > avail:
            problems.append({
                "task": r,
                "need": cumulative,
                "have": avail,
                "deficit": cumulative - avail,
            })

    return {
        "total_free": total_free,
        "total_work": total_work,
        "slack": total_free - total_work,
        "problems": problems,
        "slots": slots,
        "tasks": rows,
    }


# ----------------------------------------------------------------- đề xuất
def propose(conn, days=None, limit=None):
    """
    Xếp việc vào chỗ trống theo EDF, tham lam.

    Cố tình đơn giản. Thuật toán tối ưu toàn cục không đáng công ở đây vì
    bạn sẽ sửa tay một nửa số đề xuất, và mỗi lần sửa là kế hoạch phải
    tính lại từ đầu.
    """
    slots = [list(s) for s in free_slots(conn, days=days)]
    rows = T.open_tasks(conn)
    max_block = cfg.MAX_BLOCK_MIN * 60
    min_block = cfg.MIN_BLOCK_MIN * 60
    buf = cfg.BUFFER_MIN * 60

    out = []
    for r in rows:
        need = T.remaining(r) * 60
        if need <= 0:
            continue

        for slot in slots:
            if need <= 0:
                break
            # không xếp vượt quá hạn chót
            if r["due_ts"] and slot[0] >= r["due_ts"]:
                break

            # Vòng while, KHÔNG phải if. Một ngày trống thường là MỘT slot
            # dài 8-14 tiếng. Nếu lấy một khối rồi nhảy sang slot hôm sau,
            # mỗi việc chỉ được đúng MAX_BLOCK mỗi ngày và phần còn lại
            # lặng lẽ biến mất.
            while need > 0:
                end_cap = min(slot[1], r["due_ts"]) if r["due_ts"] else slot[1]
                avail = end_cap - slot[0]
                if avail < min_block:
                    break

                take = min(need, avail, max_block)

                # Không để lại phần dư nhỏ hơn một block. Dư 15 phút thì
                # lần sau sinh ra một block 15 phút vô dụng.
                leftover = need - take
                if 0 < leftover < min_block:
                    if avail >= need:
                        take = need
                    elif take - (min_block - leftover) >= min_block:
                        take -= (min_block - leftover)

                if take < min_block and take < need:
                    break

                out.append({
                    "task_id": r["id"],
                    "title": r["title"],
                    "start_ts": slot[0],
                    "end_ts": slot[0] + int(take),
                    "due_ts": r["due_ts"],
                })
                # Khoảng đệm SAU mỗi block agent tự xếp. Không có dòng này
                # nó sẽ đề xuất bạn học 6 tiếng liên tục không nghỉ phút nào.
                slot[0] += int(take) + buf
                need -= take

                if limit and len(out) >= limit:
                    out.sort(key=lambda p: p["start_ts"])
                    return out

    out.sort(key=lambda p: p["start_ts"])
    return out


# ------------------------------------------------------------------ hiển thị
def fmt_time(ts):
    return datetime.fromtimestamp(ts, _tz()).strftime("%H:%M")


def fmt_daytime(ts):
    d = datetime.fromtimestamp(ts, _tz())
    return d.strftime("%d/%m %H:%M")
