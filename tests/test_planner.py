"""
Kiểm thử Tầng 2.

    python tests/test_planner.py
"""

import os
import sys
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg
import inbox
import planner
import store
import tasks as T

PASS = FAIL = 0
TZ = ZoneInfo(cfg.TIMEZONE)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def ep(dt):
    return int(dt.astimezone(timezone.utc).timestamp())


def seed_event(conn, summary, start, end, is_agent=0):
    conn.execute(
        "INSERT INTO events (id, summary, start_ts, end_ts, all_day, status, "
        "is_agent, raw) VALUES (?,?,?,?,0,'confirmed',?,'{}')",
        (f"e{abs(hash((summary, ep(start)))) % 10**9}", summary,
         ep(start), ep(end), is_agent),
    )
    conn.commit()


def main():
    cfg.WORK_HOURS = (8, 22)
    cfg.MIN_BLOCK_MIN = 30
    cfg.MAX_BLOCK_MIN = 120
    cfg.BUFFER_MIN = 15
    cfg.HORIZON_DAYS = 7

    print("\n--- 1. Đọc ước tính ---")
    check("240 -> 240", T.parse_est("240") == 240)
    check("4h -> 240", T.parse_est("4h") == 240)
    check("90m -> 90", T.parse_est("90m") == 90)
    check("1h30 -> 90", T.parse_est("1h30") == 90)
    check("rác -> None", T.parse_est("abc") is None)

    print("\n--- 2. Đọc hạn chót ---")
    today = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    d = T.parse_due("mai")
    check("'mai' = ngày mai",
          datetime.fromtimestamp(d, TZ).date() == (today + timedelta(days=1)).date())
    d = T.parse_due("2026-12-31")
    check("ISO đọc được", datetime.fromtimestamp(d, TZ).strftime("%d/%m") == "31/12")
    d = T.parse_due("15/9")
    check("dd/mm đọc được", datetime.fromtimestamp(d, TZ).strftime("%d/%m") == "15/09")
    check("hạn là cuối ngày", datetime.fromtimestamp(d, TZ).hour == 23)
    check("rác -> None", T.parse_due("khi nào rảnh") is None)

    print("\n--- 3. Parser lệnh @task ---")
    p = inbox.parse_task_line("@task Viết báo cáo | 4h | 15/9")
    check("đọc đủ 3 phần", p and p["title"] == "Viết báo cáo" and p["est_min"] == 240)
    p = inbox.parse_task_line("@task Ôn thi")
    check("thiếu ước tính -> mặc định 60", p and p["est_min"] == 60)
    check("có cờ est_missing", p and p["est_missing"] is True)
    check("sự kiện thường -> None", inbox.parse_task_line("Họp nhóm") is None)

    print("\n--- 4. Tìm chỗ trống ---")
    conn = store.connect(":memory:")
    base = datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    d1 = base + timedelta(days=1)
    seed_event(conn, "Học sáng", d1.replace(hour=8), d1.replace(hour=11))
    seed_event(conn, "Họp chiều", d1.replace(hour=14), d1.replace(hour=15))

    slots = planner.free_slots(conn, days=3)
    day1 = [s for s in slots
            if datetime.fromtimestamp(s[0], TZ).date() == d1.date()]
    check("có chỗ trống ngày mai", len(day1) >= 2, f"got {len(day1)}")

    # buffer 15p: sau sự kiện 11:00 phải bắt đầu từ 11:15
    after = [s for s in day1 if datetime.fromtimestamp(s[0], TZ).hour == 11]
    check("có cộng buffer sau sự kiện",
          bool(after) and datetime.fromtimestamp(after[0][0], TZ).minute == 15,
          f"{[datetime.fromtimestamp(s[0], TZ).strftime('%H:%M') for s in day1]}")

    for s, e in slots:
        h0 = datetime.fromtimestamp(s, TZ).hour
        if datetime.fromtimestamp(e, TZ).hour != 0:
            check_hi = datetime.fromtimestamp(e, TZ).hour <= 22
        else:
            check_hi = True
        if not (h0 >= 8 and check_hi):
            check("mọi slot nằm trong giờ làm", False,
                  f"{datetime.fromtimestamp(s, TZ)} - {datetime.fromtimestamp(e, TZ)}")
            break
    else:
        check("mọi slot nằm trong giờ làm", True)

    check("không có slot ngắn hơn MIN_BLOCK",
          all((e - s) >= cfg.MIN_BLOCK_MIN * 60 for s, e in slots))

    print("\n--- 5. Khả thi: đủ thời gian ---")
    T.add(conn, "Việc nhẹ", 60, T.parse_due("mai"))
    f = planner.feasibility(conn, days=3)
    check("không báo vấn đề", len(f["problems"]) == 0, f"{f['problems']}")
    check("còn dư thời gian", f["slack"] > 0)

    print("\n--- 6. Khả thi: KHÔNG kịp ---")
    conn2 = store.connect(":memory:")
    d2 = base + timedelta(days=1)
    # Chặn HẾT hôm nay lẫn gần hết ngày mai. Không chặn hôm nay thì phần
    # trống còn lại của hôm nay đủ để mọi việc đều kịp -> test vô nghĩa.
    seed_event(conn2, "Bận hôm nay", base, base + timedelta(days=1))
    seed_event(conn2, "Bận cả ngày", d2.replace(hour=8), d2.replace(hour=21))
    T.add(conn2, "Báo cáo gấp", 600, T.parse_due("mai"))     # cần 10 tiếng
    f = planner.feasibility(conn2, days=2)
    check("phát hiện không kịp", len(f["problems"]) == 1, f"{len(f['problems'])}")
    if f["problems"]:
        check("có tính ra phần thiếu", f["problems"][0]["deficit"] > 0)

    print("\n--- 7. Khả thi tích luỹ (EDF) ---")
    conn3 = store.connect(":memory:")
    # Hai việc 150p, cùng hạn ngày mai. Chỉ còn 18:15-22:00 = 225p trống.
    # Từng việc riêng lẻ thì kịp (150 < 225). Cộng lại thì không (300 > 225).
    # Đây chính là điều mà kiểm tra từng-việc-một bỏ sót.
    dm = base + timedelta(days=1)
    seed_event(conn3, "Bận hôm nay", base, base + timedelta(days=1))
    seed_event(conn3, "Bận", dm.replace(hour=8), dm.replace(hour=18))
    T.add(conn3, "Việc A", 150, T.parse_due("mai"))
    T.add(conn3, "Việc B", 150, T.parse_due("mai"))
    f = planner.feasibility(conn3, days=2)
    avail = planner.free_minutes_before(f["slots"], T.parse_due("mai"))
    check("từng việc riêng lẻ thì vừa đủ", 150 <= avail, f"avail={avail:.0f}p")
    check("cộng dồn mới lộ ra vấn đề", len(f["problems"]) == 1,
          f"problems={len(f['problems'])}, avail={avail:.0f}p")
    if f["problems"]:
        check("báo đúng việc thứ hai",
              f["problems"][0]["task"]["title"] == "Việc B")

    print("\n--- 8. Đề xuất block ---")
    conn4 = store.connect(":memory:")
    T.add(conn4, "Ôn tập", 300, T.parse_due("mai"))     # 5 tiếng
    props = planner.propose(conn4, days=3)
    check("có sinh đề xuất", len(props) > 0)
    check("chia nhỏ theo MAX_BLOCK",
          all((p["end_ts"] - p["start_ts"]) <= cfg.MAX_BLOCK_MIN * 60 for p in props))
    check("không xếp vượt hạn",
          all(p["start_ts"] < T.parse_due("mai") for p in props))
    check("không xếp vào quá khứ",
          all(p["start_ts"] >= store.now_ts() for p in props))
    total = sum(p["end_ts"] - p["start_ts"] for p in props) / 60
    check("tổng không vượt nhu cầu", total <= 300 + 1, f"got {total}")
    check("không sinh block vụn",
          all((p["end_ts"] - p["start_ts"]) >= cfg.MIN_BLOCK_MIN * 60
              for p in props),
          f"{[(p['end_ts'] - p['start_ts']) // 60 for p in props]}")

    print("\n--- 8b. Không đề xuất block dính liền nhau ---")
    conn4b = store.connect(":memory:")
    T.add(conn4b, "Việc dài", 400, T.parse_due("mốt"))
    pr = sorted(planner.propose(conn4b, days=3), key=lambda x: x["start_ts"])
    gaps_ok = all(pr[i + 1]["start_ts"] - pr[i]["end_ts"] >= cfg.BUFFER_MIN * 60
                  or datetime.fromtimestamp(pr[i + 1]["start_ts"], TZ).date()
                  != datetime.fromtimestamp(pr[i]["end_ts"], TZ).date()
                  for i in range(len(pr) - 1))
    check("có khoảng nghỉ giữa các block", gaps_ok,
          f"{[(planner.fmt_time(p['start_ts']), planner.fmt_time(p['end_ts'])) for p in pr]}")

    print("\n--- 8c. Xếp đủ toàn bộ khối lượng, không bỏ sót ---")
    conn4c = store.connect(":memory:")
    # Một ngày trống = MỘT slot dài. Việc 6 tiếng, MAX_BLOCK 2 tiếng
    # -> phải sinh 3 block trong cùng slot đó, không phải 1.
    seed_event(conn4c, "Bận hôm nay", base, base + timedelta(days=1))
    T.add(conn4c, "Việc lớn", 360, T.parse_due("mai"))
    pr = planner.propose(conn4c, days=2)
    placed = sum(p["end_ts"] - p["start_ts"] for p in pr) / 60
    check("xếp đủ 360 phút", abs(placed - 360) < 1, f"chỉ xếp được {placed:.0f}p")
    check("chia thành nhiều block", len(pr) >= 3, f"{len(pr)} block")

    print("\n--- 8d. Nhiều việc cùng chia sẻ một ngày ---")
    conn4d = store.connect(":memory:")
    seed_event(conn4d, "Bận hôm nay", base, base + timedelta(days=1))
    T.add(conn4d, "Việc A", 240, T.parse_due("mai"))
    T.add(conn4d, "Việc B", 180, T.parse_due("mai"))
    pr = planner.propose(conn4d, days=2)
    by_task = {}
    for p in pr:
        by_task[p["task_id"]] = by_task.get(p["task_id"], 0) + \
            (p["end_ts"] - p["start_ts"]) / 60
    check("việc A được đủ 240p", abs(by_task.get(1, 0) - 240) < 1, f"{by_task}")
    check("việc B được đủ 180p", abs(by_task.get(2, 0) - 180) < 1, f"{by_task}")
    srt = sorted(pr, key=lambda x: x["start_ts"])
    check("không có block nào chồng nhau",
          all(srt[i]["end_ts"] <= srt[i + 1]["start_ts"] for i in range(len(srt) - 1)))

    print("\n--- 9. Đề xuất không chồng lên lịch đã có ---")
    conn5 = store.connect(":memory:")
    dd = base + timedelta(days=1)
    seed_event(conn5, "Họp", dd.replace(hour=14), dd.replace(hour=16))
    T.add(conn5, "Làm bài", 240, T.parse_due("mai"))
    props = planner.propose(conn5, days=2)
    busy_lo, busy_hi = ep(dd.replace(hour=14)), ep(dd.replace(hour=16))
    overlap = [p for p in props if p["start_ts"] < busy_hi and p["end_ts"] > busy_lo]
    check("không đề xuất chồng lấn", len(overlap) == 0, f"{len(overlap)} chồng")

    print("\n--- 9b. Phát hiện việc trùng ---")
    conn7 = store.connect(":memory:")
    due = T.parse_due("7/9")
    T.add(conn7, "Nộp bài tập Học Máy", 180, due)

    check("trùng y hệt", T.exists_similar(conn7, "Nộp bài tập Học Máy", due)
          is not None)
    check("khác hoa thường vẫn là trùng",
          T.exists_similar(conn7, "nộp bài tập học máy", due) is not None)
    check("thừa khoảng trắng vẫn là trùng",
          T.exists_similar(conn7, "  Nộp  bài tập   Học Máy ", due) is not None)
    # Hạn so theo NGÀY, không theo giây: gõ "7/9" hai lần cách nhau vài
    # tiếng vẫn ra cùng ngày nhưng khác timestamp.
    check("lệch vài giây vẫn là trùng",
          T.exists_similar(conn7, "Nộp bài tập Học Máy", due + 300) is not None)
    check("khác ngày thì KHÔNG trùng",
          T.exists_similar(conn7, "Nộp bài tập Học Máy",
                           T.parse_due("9/9")) is None)
    check("khác tên thì KHÔNG trùng",
          T.exists_similar(conn7, "Ôn Xác suất", due) is None)

    tid = T.add(conn7, "Việc không hạn", 60)
    check("không hạn cũng so được",
          T.exists_similar(conn7, "Việc không hạn", None) is not None)
    T.mark_done(conn7, tid)
    check("việc đã đóng không tính là trùng",
          T.exists_similar(conn7, "Việc không hạn", None) is None)

    print("\n--- 10. Ghi nhận tiến độ ---")
    conn6 = store.connect(":memory:")
    tid = T.add(conn6, "Đọc sách", 120)
    T.log_progress(conn6, tid, 50)
    check("trừ đúng phần còn lại", T.remaining(T.get(conn6, tid)) == 70)
    T.log_progress(conn6, tid, 70)
    check("hết việc -> tự đóng", T.get(conn6, tid)["status"] == "done")
    check("không còn trong danh sách mở", len(T.open_tasks(conn6)) == 0)

    print(f"\n{'=' * 46}")
    print(f"  {PASS} PASS, {FAIL} FAIL")
    print(f"{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())