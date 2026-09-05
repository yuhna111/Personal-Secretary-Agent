"""
Chạy toàn bộ agent trên bộ giả lập, không cần credentials, không cần mạng.

    python tools/demo.py
    python run.py today --db demo.db     (hoặc sửa DB_PATH tạm)

Dùng để xem agent hoạt động ra sao trước khi bạn đụng vào lịch thật.
"""

import os
import sys
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calendar_ops as ops
import config as cfg
import store
import sync
from tests.fake_calendar import FakeCalendar

DB = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "demo.db")


def iso(dt):
    return dt.isoformat()


def main():
    if os.path.exists(DB):
        os.remove(DB)

    cfg.CALENDAR_ID = "demo@example.com"
    cfg.SHADOW_MODE = True

    tz = ZoneInfo(cfg.TIMEZONE)
    d0 = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)

    cal = FakeCalendar()
    cal.seed("Giải tích 2 - giảng đường B4",
             iso(d0 + timedelta(hours=7)), iso(d0 + timedelta(hours=9, minutes=30)))
    cal.seed("Họp nhóm đồ án",
             iso(d0 + timedelta(hours=14)), iso(d0 + timedelta(hours=15)))
    cal.seed("Gym", iso(d0 + timedelta(hours=18)), iso(d0 + timedelta(hours=19)))
    cal.seed("Nộp báo cáo thực tập",
             iso(d0 + timedelta(days=2, hours=17)),
             iso(d0 + timedelta(days=2, hours=17, minutes=30)))

    conn = store.connect(DB)
    s = sync.run_sync(cal, conn, verbose=True)
    print(f"       -> bản sao có {store.count_events(conn)} sự kiện\n")

    # Agent đề xuất hai block ôn tập. Shadow mode: chỉ ghi log.
    ops.create_block(cal, conn, "Ôn Giải tích 2",
                     iso(d0 + timedelta(hours=20)), iso(d0 + timedelta(hours=21, minutes=30)),
                     reason="thi giữa kỳ còn 5 ngày, chưa có buổi ôn nào",
                     meta={"task_id": 1})
    ops.create_block(cal, conn, "Viết báo cáo thực tập",
                     iso(d0 + timedelta(days=1, hours=20)),
                     iso(d0 + timedelta(days=1, hours=22)),
                     reason="hạn nộp sau 2 ngày, ước tính cần 4 giờ",
                     meta={"task_id": 2})

    print("Đề xuất của agent (SHADOW MODE - chưa ghi lên lịch):")
    print("-" * 60)
    for r in reversed(store.recent_actions(conn, 10)):
        import json
        p = json.loads(r["payload"]) if r["payload"] else {}
        when = p.get("start", {}).get("dateTime", "")[:16].replace("T", " ")
        print(f"  + {p.get('summary', '?')}")
        print(f"      lúc  : {when}")
        print(f"      vì   : {r['reason']}")
    print(f"\n  API insert thật đã gọi: {cal.calls['insert']} lần  (đúng, shadow mode)")
    print(f"\nDB demo: {DB}. Đổi DB_PATH trong config.py sang 'demo.db'")
    print("rồi chạy  python run.py today  để xem lịch.")
    conn.close()


if __name__ == "__main__":
    main()