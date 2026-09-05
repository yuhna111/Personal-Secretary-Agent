"""
Kiểm tra sẵn sàng trước khi tắt shadow mode.

Bật quyền ghi không phải một dòng config — nó là một quyết định, và
quyết định đó nên dựa trên bằng chứng chứ không dựa trên cảm giác đã
chờ đủ lâu.

Bốn điều kiện kỹ thuật (đúng/sai rõ ràng) và hai điều kiện phán đoán
(chỉ bạn trả lời được). Module này kiểm tra bốn cái đầu và nhắc bạn về
hai cái sau.
"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import auth
import config as cfg
import store

MIN_SHADOW_ACTIONS = 15
MIN_SHADOW_DAYS = 7


def _local(ts):
    return datetime.fromtimestamp(ts, ZoneInfo(cfg.TIMEZONE))


def check(conn):
    """Trả về (list kiểm tra, số điều kiện chưa đạt)."""
    rows = conn.execute(
        "SELECT ts FROM action_log WHERE executed=0 ORDER BY ts"
    ).fetchall()
    n = len(rows)
    days = 0.0
    if n:
        days = (store.now_ts() - rows[0]["ts"]) / 86400.0

    checks = []

    # --- 1. đã tích luỹ đủ đề xuất để đánh giá chưa ---
    checks.append((
        n >= MIN_SHADOW_ACTIONS,
        f"Đã có {n} đề xuất trong shadow mode (cần ít nhất {MIN_SHADOW_ACTIONS})",
        "Chạy `python run.py plan` thêm vài lần trong những ngày tới. "
        "Mỗi lần chạy sinh ra vài đề xuất để bạn đọc.",
    ))

    # --- 2. đã trải qua đủ ngày chưa ---
    checks.append((
        days >= MIN_SHADOW_DAYS,
        f"Đã chạy shadow {days:.1f} ngày (cần ít nhất {MIN_SHADOW_DAYS})",
        "Số lượng đề xuất không thay cho thời gian. Lịch của bạn thay đổi "
        "theo tuần, và bạn cần thấy agent xử lý một tuần trọn vẹn.",
    ))

    # --- 3. scope có cho ghi không ---
    checks.append((
        auth.can_write(),
        f"Scope hiện tại: {cfg.SCOPES[0].rsplit('/', 1)[-1]}",
        'Sửa config.py:  SCOPES = ["https://www.googleapis.com/auth/calendar.events"]',
    ))

    # --- 4. lịch có được chia sẻ đủ quyền không ---
    ok_share, share_msg = _check_share()
    checks.append((
        ok_share, share_msg,
        "Google Calendar > lịch của bạn > Settings and sharing > "
        "mục Share with specific people > đổi quyền của service account "
        "thành 'Make changes to events'.",
    ))

    failed = sum(1 for ok, _, _ in checks if not ok)
    return checks, failed


def _check_share():
    """Hỏi Google xem service account đang có quyền gì trên lịch."""
    try:
        service = auth.get_calendar_service()
        items = service.calendarList().list().execute().get("items", [])
    except SystemExit:
        # auth.get_calendar_service dùng sys.exit khi thiếu file xác thực,
        # và SystemExit KHÔNG phải con của Exception nên khối dưới không
        # bắt được. Bản kiểm tra sẵn sàng thì không được phép giết chương
        # trình — nó chỉ nên báo "chưa đạt".
        return False, "Chưa có file xác thực (service_account.json)"
    except Exception as exc:
        return False, f"Không kiểm tra được quyền chia sẻ: {str(exc)[:60]}"

    for it in items:
        if it.get("id") == cfg.CALENDAR_ID:
            role = it.get("accessRole", "?")
            ok = role in ("writer", "owner")
            return ok, f"Quyền trên lịch: {role}" + ("" if ok else " (chỉ đọc)")

    return False, f"Không thấy {cfg.CALENDAR_ID} trong danh sách lịch"


JUDGEMENT = """
  Hai câu chỉ bạn trả lời được — và chúng quan trọng hơn bốn mục trên:

  1. Bạn đã ĐỌC các đề xuất chưa, hay chỉ để chúng tích lại?
     Chạy `python run.py log` và đọc từng dòng. Nếu chưa từng đọc,
     con số 15 đề xuất không có ý nghĩa gì.

  2. Trong số đã đọc, bao nhiêu phần trăm bạn thấy hợp lý?
     Trên 80% -> bật được.
     Dưới 50% -> có gì đó sai trong config hoặc trong giả định về cách
                 bạn làm việc. Sửa trước, đừng bật.
"""

STEPS = """
  Bật quyền ghi, theo ĐÚNG thứ tự này:

    1. config.py:  SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
    2. Google Calendar > Settings and sharing > đổi quyền service account
       thành "Make changes to events"
    3. python run.py check          (xác nhận vẫn kết nối được)
    4. config.py:  SHADOW_MODE = False
    5. python run.py plan --limit 2 (bắt đầu bằng HAI block, không phải sáu)
    6. Mở Google Calendar xem hai block đó
    7. Không ưng -> python run.py undo

  Bước 5 cố ý nhỏ. Lần ghi thật đầu tiên nên là thứ bạn gỡ được trong
  mười giây, không phải sáu sự kiện rải khắp tuần.
"""