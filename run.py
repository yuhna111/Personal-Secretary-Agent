"""
Điểm vào của agent.

  Kết nối
    python run.py check              kiểm tra xác thực + sync   <- chạy trước
    python run.py sync               đồng bộ một lần
    python run.py watch              vòng lặp, poll mỗi 90 giây

  Xem
    python run.py today              lịch hôm nay
    python run.py brief              BẢN TÓM TẮT — dùng cái này hàng ngày
    python run.py log                agent đã làm / định làm gì

  Công việc
    python run.py add "Viết báo cáo" --est 4h --due 30/8
    python run.py tasks              danh sách việc đang mở
    python run.py progress 1 90      ghi nhận đã làm 90 phút cho task 1
    python run.py done 1             đánh dấu xong
    python run.py inbox              nạp lệnh @task từ Google Calendar

  Xếp lịch
    python run.py plan               xếp block (theo SHADOW_MODE)
"""

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import ask as ask_mod
import auth
import calendar_ops as ops
import config as cfg
import golive as gl
import inbox
import llm
import notify
import nlu
import planner
import report
import rollback
import store
import sync
import tasks as T


def _conn():
    return store.connect(cfg.DB_PATH)


def _svc_conn():
    return auth.get_calendar_service(), _conn()


def _local(ts):
    return datetime.fromtimestamp(ts, ZoneInfo(cfg.TIMEZONE))


def _today_bounds():
    tz = ZoneInfo(cfg.TIMEZONE)
    d0 = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    return (int(d0.astimezone(timezone.utc).timestamp()),
            int((d0 + timedelta(days=1)).astimezone(timezone.utc).timestamp()),
            d0)


# ================================================================== kết nối
def cmd_check(a):
    print("Kiểm tra cấu hình\n" + "-" * 50)
    print(f"  lịch      : {cfg.CALENDAR_ID}")
    print(f"  scope     : {cfg.SCOPES[0].rsplit('/', 1)[-1]}")
    print(f"  ghi được  : {'có' if auth.can_write() else 'không (chỉ đọc)'}")
    print(f"  shadow    : {'BẬT (an toàn)' if cfg.SHADOW_MODE else 'TẮT (ghi thật)'}")
    print(f"  giờ làm   : {cfg.WORK_HOURS[0]}h - {cfg.WORK_HOURS[1]}h")

    service, conn = _svc_conn()
    try:
        sync.run_sync(service, conn)
    except Exception as exc:
        msg = str(exc)
        print(f"\nSync thất bại: {msg}")
        if "404" in msg:
            print("\n  404: CALENDAR_ID sai, hoặc chưa share lịch cho service")
            print("  account. Chạy  python whoami.py  để chẩn đoán.")
        elif "403" in msg:
            print("\n  403: chưa Enable Google Calendar API trong project.")
        return 1
    print(f"\n  Kết nối OK. Bản sao có {store.count_events(conn)} sự kiện.")
    conn.close()
    return 0


def cmd_sync(a):
    service, conn = _svc_conn()
    sync.run_sync(service, conn)
    conn.close()
    return 0


def cmd_watch(a):
    service, conn = _svc_conn()
    print(f"Đang theo dõi, poll mỗi {cfg.POLL_SECONDS}s. Ctrl+C để dừng.")
    backoff = cfg.POLL_SECONDS
    try:
        while True:
            try:
                s = sync.run_sync(service, conn, verbose=False)
                backoff = cfg.POLL_SECONDS
                if s["changed"]:
                    print(f"[{_local(store.now_ts()):%H:%M:%S}] "
                          f"{s['changed']} thay đổi từ bên ngoài")
                    for g in inbox.ingest(conn, service):
                        print(f"    @task: {g['parsed']['title']} — {g['action']}")
            except Exception as exc:
                print(f"[lỗi] {exc}  (thử lại sau {backoff}s)")
                backoff = min(backoff * 2, 900)
            time.sleep(backoff)
    except KeyboardInterrupt:
        print("\nĐã dừng.")
    finally:
        conn.close()
    return 0


# ===================================================================== xem
def _print_day(conn, lo, hi, d0):
    rows = store.events_between(conn, lo, hi)
    print(f"\nLỊCH — {d0:%A %d/%m/%Y}\n" + "-" * 50)
    if not rows:
        print("  (trống)")
    busy = 0
    for r in rows:
        mark = "[agent]" if r["is_agent"] else "       "
        if r["all_day"]:
            print(f"  {mark} cả ngày      {r['summary']}")
            continue
        busy += (r["end_ts"] - r["start_ts"]) / 60
        print(f"  {mark} {planner.fmt_time(r['start_ts'])}-"
              f"{planner.fmt_time(r['end_ts'])}  {r['summary']}")
    print(f"  Đã kín: {T.fmt_min(busy)}")


def cmd_today(a):
    conn = _conn()
    lo, hi, d0 = _today_bounds()
    _print_day(conn, lo, hi, d0)
    conn.close()
    return 0


def cmd_log(a):
    conn = _conn()
    rows = store.recent_actions(conn, 25)
    print("\nNHẬT KÝ HÀNH ĐỘNG\n" + "-" * 62)
    if not rows:
        print("  (chưa có gì)")
    for r in rows:
        state = "ĐÃ LÀM " if r["executed"] else "shadow "
        print(f"  {_local(r['ts']):%d/%m %H:%M}  {state} "
              f"{r['op']:<7} {r['reason'] or ''}")
    conn.close()
    return 0


# =============================================================== công việc
def cmd_add(a):
    conn = _conn()
    est = T.parse_est(a.est)
    if est is None:
        print(f"Không hiểu ước tính '{a.est}'. Dùng: 240 | 4h | 90m | 1h30")
        return 1
    due = T.parse_due(a.due) if a.due else None
    if a.due and due is None:
        print(f"Không hiểu hạn '{a.due}'. Dùng: 30/8 | 30/8/2026 | mai | hôm nay")
        return 1

    if _warn_duplicate(conn, a.title, due) and not a.force:
        print("\n  Không thêm. Muốn thêm nữa thì dùng cờ --force,")
        print("  hoặc sửa việc cũ bằng:  python run.py progress <số> <phút>")
        conn.close()
        return 1

    tid = T.add(conn, a.title, est, due, hard=not a.soft)
    print(f"Đã thêm việc số {T.display_no(conn, tid)}: {a.title}")
    print(f"  ước tính {T.fmt_min(est)}"
          + (f", hạn {T.fmt_due(due)}" if due else ", không hạn"))
    conn.close()
    return 0


def cmd_tasks(a):
    conn = _conn()
    rows = T.open_tasks(conn)
    print("\nCÔNG VIỆC ĐANG MỞ\n" + "-" * 62)
    if not rows:
        print('  (trống) — thêm bằng: python run.py add "Tên việc" --est 2h')
    total = 0
    now = store.now_ts()
    for i, r in enumerate(rows, 1):
        rem = T.remaining(r)
        total += rem
        left = ""
        if r["due_ts"]:
            d = (r["due_ts"] - now) / 86400
            left = (f"  hạn {T.fmt_due(r['due_ts'])} (ĐÃ QUÁ HẠN)" if d < 0
                    else f"  hạn {T.fmt_due(r['due_ts'])} ({d:.0f} ngày)")
        done = f" [đã làm {T.fmt_min(r['done_min'])}]" if r["done_min"] else ""
        print(f"  {i:<3} {r['title'][:30]:<32} còn {T.fmt_min(rem):>6}"
              f"{left}{done}")
    print(f"\n  Tổng còn lại: {T.fmt_min(total)}")
    conn.close()
    return 0


def cmd_progress(a):
    conn = _conn()
    tid = _resolve_or_hint(conn, a.task_id)
    if tid is None:
        conn.close()
        return 1
    row = T.get(conn, tid)

    # In tên TRƯỚC khi sửa dữ liệu. Số hiển thị đổi sau mỗi lần đóng việc,
    # nên đây là cách bạn phát hiện gõ nhầm trước khi số liệu bị đổi.
    print(f"{a.task_id}. {row['title']}")
    T.log_progress(conn, tid, a.minutes)
    row = T.get(conn, tid)
    rem = T.remaining(row)
    sign = "+" if a.minutes >= 0 else "-"
    print(f"  {sign}{T.fmt_min(abs(a.minutes))}")
    if rem <= 0:
        print(f"  XONG  (mở lại: python run.py reopen {tid})")
    else:
        print(f"  còn lại {T.fmt_min(rem)}")
    conn.close()
    return 0


def cmd_done(a):
    conn = _conn()
    tid = _resolve_or_hint(conn, a.task_id)
    if tid is None:
        conn.close()
        return 1
    row = T.get(conn, tid)

    T.mark_done(conn, tid)
    rem = T.remaining(row)
    print(f"Xong: {row['title']}")
    if rem > 0:
        print(f"  (còn {T.fmt_min(rem)} chưa ghi nhận — đóng sớm hơn ước tính)")

    left = T.open_tasks(conn)
    if left:
        print(f"\n  Danh sách đã đánh số lại, còn {len(left)} việc:")
        for i, r in enumerate(left[:6], 1):
            print(f"    {i}.  {r['title'][:40]}")
    else:
        print("\n  Hết việc.")
    print(f"\n  Mở lại việc vừa đóng:  python run.py reopen {tid}")
    conn.close()
    return 0


def cmd_reopen(a):
    conn = _conn()
    row = T.get(conn, a.task_id)
    if not row:
        print(f"Không có việc nào mang id {a.task_id}.")
        print("  reopen dùng ID THẬT (in ra lúc bạn đóng việc),")
        print("  không phải số thứ tự trong danh sách.")
        conn.close()
        return 1
    if row["status"] == "open":
        print(f"{row['title']} vẫn đang mở, không cần mở lại.")
        conn.close()
        return 0
    conn.execute("UPDATE tasks SET status='open' WHERE id=?", (a.task_id,))
    conn.commit()
    print(f"Đã mở lại: {row['title']}")
    print(f"  còn lại {T.fmt_min(T.remaining(row))}, "
          f"nay là việc số {T.display_no(conn, a.task_id)}")
    conn.close()
    return 0


def _warn_duplicate(conn, title, due_ts):
    """In cảnh báo nếu đã có việc y hệt. Trả True nếu trùng."""
    dup = T.exists_similar(conn, title, due_ts)
    if not dup:
        return False
    no = T.display_no(conn, dup["id"])
    print(f"\n  (!) Đã có việc y hệt: số {no} — {dup['title']}")
    print(f"      còn {T.fmt_min(T.remaining(dup))}, hạn {T.fmt_due(dup['due_ts'])}")
    return True


def _resolve_or_hint(conn, n):
    """Đổi số hiển thị sang id thật, hoặc in gợi ý rồi trả None."""
    tid = T.resolve(conn, n)
    if tid is None:
        print(f"Không có việc số {n} trong danh sách đang mở.")
        _hint_tasks(conn)
    return tid


def _hint_tasks(conn):
    rows = T.open_tasks(conn)
    if rows:
        print("\n  Các việc đang mở:")
        for i, r in enumerate(rows[:6], 1):
            print(f"    {i}.  {r['title'][:40]}")
    else:
        print("  (không còn việc nào đang mở)")
    print("\n  Xem đầy đủ:  python run.py tasks")


def cmd_inbox(a):
    service, conn = _svc_conn()
    sync.run_sync(service, conn, verbose=False)
    got = inbox.ingest(conn, service)
    print("\nNẠP LỆNH @task TỪ LỊCH\n" + "-" * 50)
    if not got:
        print("  (không có lệnh mới)")
        print(f"\n  Tạo sự kiện tên: {cfg.TASK_PREFIX} Tên việc | 240 | 30/8")
    for g in got:
        p = g["parsed"]
        print(f"  {p['title']}  ({T.fmt_min(p['est_min'])}, "
              f"hạn {T.fmt_due(p['due_ts'])}) — {g['action']}")
        if p.get("est_missing"):
            print("      (thiếu ước tính, tạm để 1h — sửa bằng lệnh add)")
    conn.close()
    return 0


# =================================================================== brief
def _deliver(subject, body, want_email):
    print("\n" + body)
    if not want_email:
        return 0
    try:
        to = notify.send(subject, body)
        print(f"\n  Đã gửi email tới {to}")
        return 0
    except notify.NotConfigured as e:
        print(f"\n  Không gửi được: {e}")
        return 1
    except Exception as e:
        print(f"\n  Gửi email thất bại: {e}")
        print("  Kiểm tra App Password, và chắc chắn đã bật xác thực 2 bước.")
        return 1


def cmd_brief(a):
    conn = _conn()
    if getattr(a, "sync", False):
        try:
            sync.run_sync(auth.get_calendar_service(), conn, verbose=False)
        except Exception as e:
            print(f"  (sync thất bại, dùng bản sao cũ: {e})")
    subject, body = report.build(conn)
    rc = _deliver(subject, body, getattr(a, "email", False))
    conn.close()
    return rc


def cmd_review(a):
    conn = _conn()
    subject, body = report.build_review(conn)
    rc = _deliver(subject, body, getattr(a, "email", False))
    conn.close()
    return rc


def cmd_plan(a):
    service, conn = _svc_conn()
    props = planner.propose(conn, limit=a.limit)
    if not props:
        print("Không có gì để xếp.")
        return 0

    print(f"\nXẾP {len(props)} BLOCK "
          f"({'SHADOW MODE' if cfg.SHADOW_MODE else 'GHI THẬT'})\n" + "-" * 50)

    # Ghi thật thì cho xem trước rồi mới hỏi. Shadow mode không cần —
    # nó vốn không đụng gì tới lịch.
    if not cfg.SHADOW_MODE and not a.yes:
        for p in props:
            print(f"  {planner.fmt_daytime(p['start_ts'])}-"
                  f"{planner.fmt_time(p['end_ts'])}  {p['title'][:30]}")
        print("\n  Các block này sẽ được GHI THẬT lên Google Calendar.")
        if input("  Tiếp tục? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  Đã huỷ.")
            conn.close()
            return 0
        print()

    for p in props:
        reason = f"task #{p['task_id']}"
        if p["due_ts"]:
            reason += f", hạn {T.fmt_due(p['due_ts'])}"
        try:
            ops.create_block(
                service, conn, p["title"],
                _local(p["start_ts"]).isoformat(),
                _local(p["end_ts"]).isoformat(),
                reason=reason, meta={"task_id": p["task_id"]},
            )
            print(f"  OK   {planner.fmt_daytime(p['start_ts'])}  {p['title'][:28]}")
        except ops.Blocked as e:
            print(f"  CHẶN {planner.fmt_daytime(p['start_ts'])}  "
                  f"{p['title'][:22]} — {e}")
    print("\n  Xem lại:  python run.py log")
    if not cfg.SHADOW_MODE:
        print("  Không ưng:  python run.py undo -n " + str(len(props)))
    conn.close()
    return 0



# ==================================================================== LLM
def _need_llm():
    if llm.available():
        return True
    print(llm.setup_hint())
    return False


def cmd_llm(a):
    """Xem đang dùng nhà cung cấp nào, và thử một lời gọi thật."""
    print(f"Nhà cung cấp : {llm.describe()}")
    print(f"Sẵn sàng     : {'có' if llm.available() else 'KHÔNG'}")
    if not llm.available():
        print()
        print(llm.setup_hint())
        return 1
    print("\n  Đang thử gọi thật...")
    try:
        # 400 token chứ không phải 50: model Gemini đời mới tiêu phần lớn
        # token cho bước suy luận nội bộ trước khi viết ra chữ nào. Đặt
        # thấp quá thì HTTP 200 mà nội dung rỗng — trông như hỏng.
        r = llm.complete("Trả lời ngắn gọn.", "Thủ đô Việt Nam là gì?",
                         llm.PROBE_TOKENS)
        if not r.strip():
            print("  Gọi được nhưng model trả về rỗng.")
            print("  Thử:  python run.py ask \"tôi còn bao nhiêu việc?\"")
            return 1
        print(f"  Trả lời: {r.strip()[:80]}")
        print(f"  OK — {llm.describe()}")
        return 0
    except Exception as exc:
        print(f"  Thất bại: {exc}")
        return 1


def cmd_note(a):
    """Nhập việc bằng câu tiếng Việt tự nhiên."""
    if not _need_llm():
        return 1
    conn = _conn()
    try:
        r = nlu.parse_task(a.text)
    except Exception as exc:
        print(f"Không hiểu câu này: {exc}")
        conn.close()
        return 1

    print(f"\n  Hiểu là : {r['note'] or '—'}")
    print(f"  Tên việc: {r['title']}")
    print(f"  Ước tính: {T.fmt_min(r['est_min'])}")
    print(f"  Hạn     : {T.fmt_due(r['due_ts'])}")
    for w in r["warnings"]:
        print(f"  (!) {w}")

    dup = _warn_duplicate(conn, r["title"], r["due_ts"])

    if not a.yes:
        if dup:
            print("\n  Vẫn thêm việc trùng này? [y/N] ", end="")
            if input().strip().lower() not in ("y", "yes"):
                print("  Đã huỷ.")
                conn.close()
                return 0
            tid = T.add(conn, r["title"], r["est_min"], r["due_ts"], source="cli")
            print(f"\n  Đã thêm việc số {T.display_no(conn, tid)}")
            conn.close()
            return 0
        if input("\n  Thêm việc này? [Y/n] ").strip().lower() in ("n", "no"):
            print("  Đã huỷ.")
            conn.close()
            return 0

    tid = T.add(conn, r["title"], r["est_min"], r["due_ts"], source="cli")
    # Số thứ tự hiển thị, không phải id thật — để khớp với `add` và `tasks`.
    print(f"\n  Đã thêm việc số {T.display_no(conn, tid)}")
    conn.close()
    return 0


def cmd_ask(a):
    """Hỏi đáp trên chính dữ liệu của bạn."""
    if not _need_llm():
        return 1
    try:
        r = ask_mod.ask(a.question, verbose=a.sql)
    except Exception as exc:
        print(f"Không trả lời được: {exc}")
        return 1
    print(f"\n{r['answer']}\n")
    if a.sql:
        print(f"  ({len(r['rows'])} hàng)")
    return 0



# ================================================================ Tầng 5
def cmd_undo(a):
    """Gỡ các hành động agent đã ghi thật lên lịch."""
    service, conn = _svc_conn()
    rows = store.undoable_actions(conn, a.n)
    if not rows:
        print("Không có hành động nào để gỡ.")
        print("  (chỉ gỡ được thao tác ĐÃ GHI THẬT; đề xuất trong shadow")
        print("   mode không đụng tới lịch nên không cần gỡ)")
        conn.close()
        return 0

    print(f"\nSẼ GỠ {len(rows)} hành động\n" + "-" * 52)
    for r in rows:
        ok, desc = rollback.undo_one(service, conn, r, dry_run=True)
        print(f"  {_local(r['ts']):%d/%m %H:%M}  {r['op']:<7} "
              f"{r['reason'] or ''} -> {desc}")

    if not a.yes:
        if input("\n  Tiến hành gỡ? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  Đã huỷ.")
            conn.close()
            return 0

    print()
    n_ok = 0
    for r in rows:
        ok, desc = rollback.undo_one(service, conn, r)
        print(f"  {'OK  ' if ok else 'HỎNG'} {desc}")
        n_ok += ok
    print(f"\n  Gỡ được {n_ok}/{len(rows)}.")
    conn.close()
    return 0


def cmd_cleanup(a):
    """Xoá block của những việc đã xong hoặc đã bỏ."""
    service, conn = _svc_conn()
    sync.run_sync(service, conn, verbose=False)

    stale = rollback.find_stale(conn)
    if not stale:
        print("Không có block nào cần dọn.")
        conn.close()
        return 0

    print(f"\n{len(stale)} BLOCK KHÔNG CÒN LÝ DO TỒN TẠI\n" + "-" * 52)
    for ev, why in stale:
        print(f"  {planner.fmt_daytime(ev['start_ts'])}  "
              f"{(ev['summary'] or '')[:30]:<32} {why}")

    if cfg.SHADOW_MODE:
        print("\n  SHADOW MODE đang bật -> không xoá gì cả.")
        conn.close()
        return 0

    if not a.yes:
        if input("\n  Xoá các block này? [y/N] ").strip().lower() not in ("y", "yes"):
            print("  Đã huỷ.")
            conn.close()
            return 0

    print()
    for name, why, ok in rollback.cleanup(service, conn):
        print(f"  {'OK  ' if ok else 'HỎNG'} {(name or '')[:34]:<36} {why}")
    conn.close()
    return 0


def cmd_golive(a):
    """Kiểm tra đã sẵn sàng tắt shadow mode chưa."""
    conn = _conn()
    print("\nSẴN SÀNG BẬT QUYỀN GHI?\n" + "=" * 52)

    if not cfg.SHADOW_MODE:
        print("\n  SHADOW_MODE đã TẮT — agent đang ghi thật lên lịch.")
        print("  Gỡ lại:  python run.py undo")
        conn.close()
        return 0

    checks, failed = gl.check(conn)
    print()
    for ok, msg, fix in checks:
        print(f"  [{'x' if ok else ' '}] {msg}")
        if not ok:
            for line in fix.split(". "):
                if line.strip():
                    print(f"        {line.strip().rstrip('.')}.")
    print(gl.JUDGEMENT)

    if failed:
        print(f"  Còn {failed} điều kiện chưa đạt. Chưa nên bật.")
    else:
        print("  Bốn điều kiện kỹ thuật đều đạt.")
        print(gl.STEPS)
    conn.close()
    return 0 if failed == 0 else 1


# ================================================================== parser
def build_parser():
    p = argparse.ArgumentParser(prog="run.py", description="Agent thư ký cá nhân")
    sub = p.add_subparsers(dest="cmd")

    for name, fn, help_ in [
        ("check", cmd_check, "kiểm tra xác thực + sync"),
        ("sync", cmd_sync, "đồng bộ một lần"),
        ("watch", cmd_watch, "vòng lặp theo dõi"),
        ("today", cmd_today, "lịch hôm nay"),
        ("log", cmd_log, "nhật ký hành động"),
        ("tasks", cmd_tasks, "danh sách việc"),
        ("inbox", cmd_inbox, "nạp lệnh @task từ lịch"),
        ("llm", cmd_llm, "kiểm tra cấu hình LLM"),
        ("golive", cmd_golive, "kiểm tra sẵn sàng bật quyền ghi"),
    ]:
        sp = sub.add_parser(name, help=help_)
        sp.set_defaults(func=fn)

    sp = sub.add_parser("brief", help="bản tóm tắt đầy đủ")
    sp.add_argument("--email", action="store_true", help="gửi qua email")
    sp.add_argument("--sync", action="store_true", help="đồng bộ trước khi dựng")
    sp.set_defaults(func=cmd_brief)

    sp = sub.add_parser("review", help="đối chiếu cuối ngày")
    sp.add_argument("--email", action="store_true", help="gửi qua email")
    sp.set_defaults(func=cmd_review)

    sp = sub.add_parser("note", help="nhập việc bằng câu tiếng Việt (cần LLM)")
    sp.add_argument("text")
    sp.add_argument("-y", "--yes", action="store_true", help="không hỏi xác nhận")
    sp.set_defaults(func=cmd_note)

    sp = sub.add_parser("ask", help="hỏi về dữ liệu của bạn (cần LLM)")
    sp.add_argument("question")
    sp.add_argument("--sql", action="store_true", help="in cả câu SQL")
    sp.set_defaults(func=cmd_ask)

    sp = sub.add_parser("add", help="thêm việc")
    sp.add_argument("title")
    sp.add_argument("--est", required=True, help="240 | 4h | 90m | 1h30")
    sp.add_argument("--due", help="30/8 | 30/8/2026 | mai | hôm nay")
    sp.add_argument("--soft", action="store_true", help="hạn mong muốn, không cứng")
    sp.add_argument("--force", action="store_true", help="thêm dù đã có việc trùng")
    sp.set_defaults(func=cmd_add)

    sp = sub.add_parser("progress", help="ghi nhận thời gian đã làm")
    sp.add_argument("task_id", type=int, help="số thứ tự trong 'run.py tasks'")
    sp.add_argument("minutes", type=float)
    sp.set_defaults(func=cmd_progress)

    sp = sub.add_parser("done", help="đánh dấu xong")
    sp.add_argument("task_id", type=int, help="số thứ tự trong 'run.py tasks'")
    sp.set_defaults(func=cmd_done)

    sp = sub.add_parser("reopen", help="mở lại việc đã đóng")
    sp.add_argument("task_id", type=int, help="ID THẬT, in ra lúc đóng việc")
    sp.set_defaults(func=cmd_reopen)

    sp = sub.add_parser("plan", help="xếp block vào lịch")
    sp.add_argument("--limit", type=int, default=6)
    sp.add_argument("-y", "--yes", action="store_true", help="không hỏi xác nhận")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("undo", help="gỡ hành động agent đã ghi")
    sp.add_argument("-n", type=int, default=1, help="gỡ mấy hành động gần nhất")
    sp.add_argument("-y", "--yes", action="store_true")
    sp.set_defaults(func=cmd_undo)

    sp = sub.add_parser("cleanup", help="xoá block của việc đã xong")
    sp.add_argument("-y", "--yes", action="store_true")
    sp.set_defaults(func=cmd_cleanup)

    return p


if __name__ == "__main__":
    parser = build_parser()
    args = parser.parse_args()
    if not getattr(args, "func", None):
        parser.print_help()
        sys.exit(0)
    sys.exit(args.func(args))