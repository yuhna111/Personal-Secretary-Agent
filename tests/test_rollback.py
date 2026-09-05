"""
Kiểm thử Tầng 5.

    python tests/test_rollback.py

Đây là tầng nguy hiểm nhất trong cả dự án: nó XOÁ sự kiện trên lịch thật.
Nên phần lớn phép thử dưới đây không kiểm tra "nó có làm được không" mà
kiểm tra "nó có TỪ CHỐI đúng lúc không".
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import calendar_ops as ops
import config as cfg
import golive as gl
import rollback
import store
import tasks as T
from tests.fake_calendar import FakeCalendar

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def setup():
    cfg.CALENDAR_ID = "test@example.com"
    cfg.SHADOW_MODE = False
    cfg.SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
    cfg.QUIET_HOURS = (23, 23)
    cfg.MAX_WRITES_PER_DAY = 50
    return FakeCalendar(), store.connect(":memory:")


def sync_in(cal, conn):
    import sync
    store.set_state(conn, "sync_token", None)
    conn.commit()
    sync.run_sync(cal, conn, verbose=False)


def main():
    print("\n--- 1. Gỡ một block vừa tạo ---")
    cal, conn = setup()
    ev = ops.create_block(cal, conn, "Ôn tập",
                          "2026-09-10T20:00:00+07:00", "2026-09-10T22:00:00+07:00",
                          reason="test", meta={"task_id": 1}, dry_run=False)
    check("đã tạo trên lịch", ev["id"] in cal.store)

    rows = store.undoable_actions(conn)
    check("có 1 hành động gỡ được", len(rows) == 1, f"{len(rows)}")

    ok, desc = rollback.undo_one(cal, conn, rows[0])
    check("gỡ thành công", ok, desc)
    check("sự kiện đã bị huỷ trên lịch",
          cal.store[ev["id"]]["status"] == "cancelled")
    check("không gỡ lại lần hai", len(store.undoable_actions(conn)) == 0)

    print("\n--- 2. Đề xuất shadow KHÔNG nằm trong danh sách gỡ ---")
    cal, conn = setup()
    cfg.SHADOW_MODE = True
    ops.create_block(cal, conn, "X", "2026-09-10T20:00:00+07:00",
                     "2026-09-10T21:00:00+07:00", reason="test")
    check("shadow không sinh việc phải gỡ",
          len(store.undoable_actions(conn)) == 0)
    check("nhưng vẫn có trong nhật ký", len(store.recent_actions(conn)) == 1)
    cfg.SHADOW_MODE = False

    print("\n--- 3. Gỡ khi bạn đã tự xoá tay trên lịch ---")
    cal, conn = setup()
    ev = ops.create_block(cal, conn, "Y", "2026-09-10T20:00:00+07:00",
                          "2026-09-10T21:00:00+07:00", reason="test",
                          dry_run=False)
    del cal.store[ev["id"]]                     # bạn xoá thẳng trên Calendar
    ok, desc = rollback.undo_one(cal, conn, store.undoable_actions(conn)[0])
    check("không báo lỗi", ok, desc)
    check("hiểu là đã bị xoá tay", "xoá tay" in desc, desc)
    check("đánh dấu xong, không thử lại mãi",
          len(store.undoable_actions(conn)) == 0)

    print("\n--- 4. Gỡ thao tác dời block ---")
    cal, conn = setup()
    ev = ops.create_block(cal, conn, "Z", "2026-09-10T20:00:00+07:00",
                          "2026-09-10T21:00:00+07:00", reason="tạo",
                          dry_run=False)
    sync_in(cal, conn)
    ops.move_block(cal, conn, ev["id"], "2026-09-11T08:00:00+07:00",
                   "2026-09-11T09:00:00+07:00", reason="dời", dry_run=False)
    check("đã dời trên lịch",
          cal.store[ev["id"]]["start"]["dateTime"].startswith("2026-09-11"))

    latest = store.undoable_actions(conn)[0]
    check("hành động mới nhất là patch", latest["op"] == "patch")
    ok, _ = rollback.undo_one(cal, conn, latest)
    check("gỡ được lệnh dời", ok)
    check("giờ đã quay về ban đầu",
          cal.store[ev["id"]]["start"]["dateTime"].startswith("2026-09-10"),
          cal.store[ev["id"]]["start"]["dateTime"])

    print("\n--- 5. Dọn block của việc đã xong ---")
    cal, conn = setup()
    t1 = T.add(conn, "Việc còn làm", 120)
    t2 = T.add(conn, "Việc đã xong", 120)
    future = "2027-01-10T20:00:00+07:00"
    ops.create_block(cal, conn, "Việc còn làm", future,
                     "2027-01-10T21:00:00+07:00", reason="a",
                     meta={"task_id": t1}, dry_run=False)
    ops.create_block(cal, conn, "Việc đã xong", "2027-01-11T20:00:00+07:00",
                     "2027-01-11T21:00:00+07:00", reason="b",
                     meta={"task_id": t2}, dry_run=False)
    sync_in(cal, conn)

    check("chưa có gì để dọn", len(rollback.find_stale(conn)) == 0)

    T.mark_done(conn, t2)
    stale = rollback.find_stale(conn)
    check("phát hiện đúng 1 block thừa", len(stale) == 1, f"{len(stale)}")
    if stale:
        check("đúng block của việc đã xong",
              stale[0][0]["summary"] == "Việc đã xong")

    res = rollback.cleanup(cal, conn)
    check("dọn thành công", len(res) == 1 and res[0][2])
    check("block còn lại không bị đụng",
          len(rollback.find_stale(conn)) == 0)

    print("\n--- 6. KHÔNG dọn block trong quá khứ ---")
    cal, conn = setup()
    t = T.add(conn, "Việc cũ", 60)
    ops.create_block(cal, conn, "Việc cũ", "2020-01-01T20:00:00+07:00",
                     "2020-01-01T21:00:00+07:00", reason="c",
                     meta={"task_id": t}, dry_run=False)
    sync_in(cal, conn)
    T.mark_done(conn, t)
    check("block quá khứ là lịch sử, giữ nguyên",
          len(rollback.find_stale(conn)) == 0)

    print("\n--- 7. KHÔNG đụng vào sự kiện của người dùng ---")
    cal, conn = setup()
    cal.seed("Sinh nhật bạn", "2027-02-01T18:00:00+07:00",
             "2027-02-01T20:00:00+07:00")
    sync_in(cal, conn)
    check("sự kiện người dùng không bị coi là rác",
          len(rollback.find_stale(conn)) == 0)

    # ngay cả khi nó vô tình mang task_id
    cal.seed("Giả mạo", "2027-02-02T18:00:00+07:00",
             "2027-02-02T19:00:00+07:00", private={"task_id": "999"})
    sync_in(cal, conn)
    check("thiếu nhãn agent -> vẫn bỏ qua",
          len(rollback.find_stale(conn)) == 0,
          f"{[s[0]['summary'] for s in rollback.find_stale(conn)]}")

    print("\n--- 8. Kiểm tra sẵn sàng: chặn khi chưa đủ điều kiện ---")
    cal, conn = setup()
    cfg.SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
    checks, failed = gl.check(conn)
    check("báo chưa đạt khi chưa có dữ liệu", failed >= 2, f"failed={failed}")
    names = " ".join(m for _, m, _ in checks)
    check("có kiểm tra số đề xuất", "đề xuất" in names)
    check("có kiểm tra số ngày", "ngày" in names)
    check("có kiểm tra scope", "readonly" in names)

    print("\n--- 9. Kiểm tra sẵn sàng: đạt điều kiện đếm được ---")
    cal, conn = setup()
    old = store.now_ts() - 10 * 86400
    for i in range(gl.MIN_SHADOW_ACTIONS + 2):
        conn.execute(
            "INSERT INTO action_log (ts, op, reason, executed) VALUES (?,?,?,0)",
            (old + i * 3600, "insert", f"đề xuất {i}"))
    conn.commit()
    checks, failed = gl.check(conn)
    passed = [m for ok, m, _ in checks if ok]
    check("đạt mốc số lượng đề xuất",
          any("đề xuất" in m for m in passed), f"{passed}")
    check("đạt mốc số ngày", any("ngày" in m for m in passed), f"{passed}")

    print(f"\n{'=' * 46}")
    print(f"  {PASS} PASS, {FAIL} FAIL")
    print(f"{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())