"""
Kiểm thử Tầng 1 trên bộ giả lập.

    python tests/test_agent.py

Kiểm chứng 8 hành vi. Ba cái quan trọng nhất:
  - sync tăng dần thật sự chỉ trả về phần đã đổi
  - agent KHÔNG phản ứng với chính thay đổi của mình
  - các cầu dao an toàn thật sự chặn được
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config as cfg
import store
import sync
import calendar_ops as ops
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


def fresh_db():
    if os.path.exists(":memory:"):
        pass
    return store.connect(":memory:")


def main():
    cfg.CALENDAR_ID = "test@example.com"
    cfg.SHADOW_MODE = True

    cal = FakeCalendar()
    cal.seed("Học Giải tích", "2026-08-27T19:00:00+07:00", "2026-08-27T21:00:00+07:00")
    cal.seed("Họp nhóm đồ án", "2026-08-28T09:00:00+07:00", "2026-08-28T10:30:00+07:00")
    conn = fresh_db()

    print("\n--- 1. Full sync lần đầu ---")
    s = sync.run_sync(cal, conn, verbose=False)
    check("kéo về đủ 2 sự kiện", store.count_events(conn) == 2,
          f"got {store.count_events(conn)}")
    check("đánh dấu là full sync", s["full"] is True)
    check("đã lưu syncToken", store.get_state(conn, "sync_token") is not None)

    print("\n--- 2. Sync khi không có gì đổi ---")
    before = cal.calls["list"]
    s = sync.run_sync(cal, conn, verbose=False)
    check("không báo thay đổi nào", s["changed"] == 0, f"got {s['changed']}")
    check("chỉ tốn 1 lần gọi API", cal.calls["list"] == before + 1)

    print("\n--- 3. Người dùng thêm sự kiện ngoài agent ---")
    cal.seed("Đi khám răng", "2026-08-29T14:00:00+07:00", "2026-08-29T15:00:00+07:00")
    s = sync.run_sync(cal, conn, verbose=False)
    check("phát hiện đúng 1 thay đổi", s["changed"] == 1, f"got {s['changed']}")
    check("bản sao có 3 sự kiện", store.count_events(conn) == 3)

    print("\n--- 4. Shadow mode: chỉ ghi log, không gọi API ---")
    ins_before = cal.calls["insert"]
    r = ops.create_block(cal, conn, "Ôn tập Xác suất",
                         "2026-08-30T20:00:00+07:00", "2026-08-30T22:00:00+07:00",
                         reason="còn 3 ngày tới kỳ thi", meta={"task_id": 7})
    check("trả về cờ shadow", r.get("shadow") is True)
    check("KHÔNG gọi API insert", cal.calls["insert"] == ins_before)
    log = store.recent_actions(conn, 1)[0]
    check("có ghi action_log", log["op"] == "insert")
    check("đánh dấu chưa thực thi", log["executed"] == 0)

    print("\n--- 5. Cầu dao: scope chỉ đọc thì chặn ghi thật ---")
    cfg.SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
    try:
        ops.create_block(cal, conn, "X", "2026-08-30T20:00:00+07:00",
                         "2026-08-30T21:00:00+07:00", reason="test", dry_run=False)
        check("chặn ghi khi scope readonly", False, "không raise")
    except ops.Blocked as e:
        check("chặn ghi khi scope readonly", "readonly" in str(e))

    print("\n--- 6. Ghi thật khi đã đủ quyền ---")
    cfg.SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
    cfg.QUIET_HOURS = (23, 23)          # tắt giờ yên tĩnh để test
    ev = ops.create_block(cal, conn, "Ôn tập Xác suất",
                          "2026-08-30T20:00:00+07:00", "2026-08-30T22:00:00+07:00",
                          reason="còn 3 ngày tới kỳ thi",
                          meta={"task_id": 7}, dry_run=False)
    check("đã gọi API insert", cal.calls["insert"] == ins_before + 1)
    check("sự kiện mang nhãn agent",
          ev["extendedProperties"]["private"][cfg.AGENT_TAG] == cfg.AGENT_VERSION)
    check("meta nằm trên sự kiện",
          ev["extendedProperties"]["private"]["task_id"] == "7")

    print("\n--- 7. Chống vòng lặp: agent không phản ứng với chính mình ---")
    s = sync.run_sync(cal, conn, verbose=False)
    check("nhận ra là tự-ghi", s["self"] == 1, f"self={s['self']}")
    check("KHÔNG tính là thay đổi ngoài", s["changed"] == 0, f"changed={s['changed']}")
    check("vẫn lưu vào bản sao", store.count_events(conn) == 4)

    print("\n--- 8. Từ chối đụng vào sự kiện của người dùng ---")
    user_ev = conn.execute(
        "SELECT id FROM events WHERE is_agent=0 LIMIT 1").fetchone()["id"]
    try:
        ops.remove_block(cal, conn, user_ev, reason="test", dry_run=False)
        check("từ chối xoá sự kiện người dùng", False, "không raise")
    except ops.Blocked as e:
        check("từ chối xoá sự kiện người dùng", "không do agent" in str(e))

    print("\n--- 9. Cầu dao: giờ yên tĩnh ---")
    cfg.QUIET_HOURS = (0, 24)           # ép luôn nằm trong giờ yên tĩnh
    try:
        ops.create_block(cal, conn, "X", "2026-08-31T20:00:00+07:00",
                         "2026-08-31T21:00:00+07:00", reason="test", dry_run=False)
        check("chặn ghi ban đêm", False, "không raise")
    except ops.Blocked as e:
        check("chặn ghi ban đêm", "yên tĩnh" in str(e))
    cfg.QUIET_HOURS = (23, 23)

    print("\n--- 10. Cầu dao: trần thao tác mỗi ngày ---")
    cfg.MAX_WRITES_PER_DAY = 1          # đã ghi 1 lần ở bước 6
    try:
        ops.create_block(cal, conn, "X", "2026-08-31T20:00:00+07:00",
                         "2026-08-31T21:00:00+07:00", reason="test", dry_run=False)
        check("chặn khi chạm trần", False, "không raise")
    except ops.Blocked as e:
        check("chặn khi chạm trần", "trần" in str(e))
    cfg.MAX_WRITES_PER_DAY = 20

    print("\n--- 11. syncToken hết hạn -> tự full sync lại ---")
    cal.expire_tokens()
    s = sync.run_sync(cal, conn, verbose=False)
    check("tự chuyển sang full sync", s["full"] is True)
    check("bản sao vẫn đúng", store.count_events(conn) == 4,
          f"got {store.count_events(conn)}")

    print("\n--- 12. Xoá phía Google -> gỡ khỏi bản sao ---")
    agent_ev = conn.execute(
        "SELECT id FROM events WHERE is_agent=1 LIMIT 1").fetchone()["id"]
    cal.delete("x", agent_ev).execute()
    s = sync.run_sync(cal, conn, verbose=False)
    check("phát hiện sự kiện bị xoá", s["deleted"] == 1, f"got {s['deleted']}")
    check("bản sao còn 3", store.count_events(conn) == 3)

    print(f"\n{'=' * 46}")
    print(f"  {PASS} PASS, {FAIL} FAIL")
    print(f"{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
