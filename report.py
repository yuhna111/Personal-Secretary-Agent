"""
Dựng nội dung bản tóm tắt.

Tách khỏi run.py vì cùng một nội dung phải đi ra hai đường: in ra terminal,
và gửi qua email. Nếu để logic nằm trong hàm print thì bản email sẽ dần
lệch khỏi bản terminal — lỗi kinh điển của mọi hệ thống báo cáo.

Ở đây chỉ dựng chuỗi. Không gọi API, không gửi đi đâu.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import config as cfg
import planner
import store
import tasks as T

W = 52


def _tz():
    return ZoneInfo(cfg.TIMEZONE)


def _today_bounds():
    d0 = datetime.now(_tz()).replace(hour=0, minute=0, second=0, microsecond=0)
    return (int(d0.astimezone(timezone.utc).timestamp()),
            int((d0 + timedelta(days=1)).astimezone(timezone.utc).timestamp()),
            d0)


def _day_section(conn, lo, hi, d0):
    L = [f"LỊCH — {d0:%A %d/%m/%Y}", "-" * W]
    rows = store.events_between(conn, lo, hi)
    if not rows:
        L.append("  (trống)")
    busy = 0
    for r in rows:
        mark = "[agent]" if r["is_agent"] else "       "
        if r["all_day"]:
            L.append(f"  {mark} cả ngày      {r['summary']}")
            continue
        busy += (r["end_ts"] - r["start_ts"]) / 60
        L.append(f"  {mark} {planner.fmt_time(r['start_ts'])}-"
                 f"{planner.fmt_time(r['end_ts'])}  {r['summary']}")
    L.append(f"  Đã kín: {T.fmt_min(busy)}")
    return L


def build(conn, include_proposals=True):
    """Trả về (tiêu_đề, nội_dung). Tiêu đề dùng cho subject email."""
    lo, hi, d0 = _today_bounds()
    now = store.now_ts()

    L = _day_section(conn, lo, hi, d0)

    f = planner.feasibility(conn)
    rows = f["tasks"]

    L += ["", f"CÔNG VIỆC — {len(rows)} việc, còn {T.fmt_min(f['total_work'])}",
          "-" * W]
    if not rows:
        L.append("  (trống)")
    for i, r in enumerate(rows[:8], 1):
        due = f"hạn {T.fmt_due(r['due_ts'])}" if r["due_ts"] else "không hạn"
        if r["due_ts"] and r["due_ts"] < now:
            due += " QUÁ HẠN"
        L.append(f"  {i:<3} {r['title'][:28]:<30} "
                 f"còn {T.fmt_min(T.remaining(r)):>6}   {due}")
    if len(rows) > 8:
        L.append(f"  ... và {len(rows) - 8} việc nữa")

    L += ["", f"KHẢ THI — {cfg.HORIZON_DAYS} ngày tới", "-" * W,
          f"  Thời gian trống : {T.fmt_min(f['total_free'])}",
          f"  Việc còn lại    : {T.fmt_min(f['total_work'])}"]
    L.append(f"  Dư              : {T.fmt_min(f['slack'])}" if f["slack"] >= 0
             else f"  THIẾU           : {T.fmt_min(-f['slack'])}")

    headline = "ổn"
    if f["problems"]:
        headline = f"{len(f['problems'])} việc không kịp"
        L += ["", "  KHÔNG KỊP:"]
        pos = {r["id"]: i for i, r in enumerate(rows, 1)}
        for p in f["problems"]:
            t = p["task"]
            L.append(f"    {pos.get(t['id'], '?')}. {t['title'][:28]}")
            L.append(f"       cần {T.fmt_min(p['need'])} trước "
                     f"{T.fmt_due(t['due_ts'])}, chỉ có {T.fmt_min(p['have'])}"
                     f" -> thiếu {T.fmt_min(p['deficit'])}")
        L += ["", "  ('cần' là con số tích luỹ, gồm cả việc hạn sớm hơn,",
              "   vì bạn không làm hai việc cùng lúc được)"]
    elif rows:
        L += ["", "  Mọi việc đều kịp hạn."]

    if include_proposals:
        props = planner.propose(conn, limit=6)
        if props:
            tag = "SHADOW — chưa ghi lên lịch" if cfg.SHADOW_MODE else "sẽ ghi thật"
            L += ["", f"ĐỀ XUẤT ({tag})", "-" * W]
            for p in props:
                mins = (p["end_ts"] - p["start_ts"]) / 60
                L.append(f"  {planner.fmt_daytime(p['start_ts'])}-"
                         f"{planner.fmt_time(p['end_ts'])}  "
                         f"{p['title'][:26]:<28} ({T.fmt_min(mins)})")

    subject = f"Tóm tắt {d0:%d/%m} — {headline}"
    return subject, "\n".join(L)


def build_review(conn):
    """
    Bản đối chiếu buổi tối: agent đã đề xuất/làm gì trong ngày hôm nay.
    Đây là thứ bạn đọc trong suốt shadow mode để quyết định có tin nó không.
    """
    lo, _, d0 = _today_bounds()
    rows = [r for r in store.recent_actions(conn, 100) if r["ts"] >= lo]

    L = [f"ĐỐI CHIẾU — {d0:%d/%m/%Y}", "-" * W]
    if not rows:
        L.append("  Hôm nay agent không đề xuất gì.")
        return f"Đối chiếu {d0:%d/%m}", "\n".join(L)

    shadow = sum(1 for r in rows if not r["executed"])
    real = len(rows) - shadow
    L.append(f"  {len(rows)} hành động: {real} đã làm, {shadow} chỉ đề xuất")
    L.append("")
    for r in reversed(rows):
        state = "ĐÃ LÀM " if r["executed"] else "đề xuất"
        t = datetime.fromtimestamp(r["ts"], _tz())
        L.append(f"  {t:%H:%M}  {state}  {r['op']:<7} {r['reason'] or ''}")

    L += ["", "  Đề xuất nào vô lý? Sửa WORK_HOURS / MAX_BLOCK_MIN trong",
          "  config.py, hoặc thêm sự kiện cố định lên Google Calendar."]
    return f"Đối chiếu {d0:%d/%m}", "\n".join(L)