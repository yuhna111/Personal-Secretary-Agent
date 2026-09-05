"""
Chẩn đoán quyền truy cập lịch.

    python tools/whoami.py

Hỏi thẳng Google ba câu:
  1. Tôi đang đăng nhập với danh tính nào?
  2. Danh tính đó nhìn thấy những lịch nào?
  3. Có vào được đúng CALENDAR_ID trong config không?

Chạy cái này khi run.py check báo 404 hoặc 403.
"""

import json
import os
import sys


# Chạy được từ bất cứ đâu: thêm thư mục gốc dự án vào đường dẫn tìm module.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import auth
import config as cfg


def main():
    print("=" * 62)
    print("  CHẨN ĐOÁN QUYỀN TRUY CẬP LỊCH")
    print("=" * 62)

    # ---------------------------------------------------------- 1. danh tính
    sa_path = os.path.join(cfg.BASE_DIR, cfg.SERVICE_ACCOUNT_FILE)
    sa_email = None
    if os.path.exists(sa_path):
        with open(sa_path, encoding="utf-8") as f:
            data = json.load(f)
        sa_email = data.get("client_email")
        print("\n[1] Service account đang dùng")
        print(f"    {sa_email}")
        print(f"    project: {data.get('project_id')}")
        print("\n    >>> Địa chỉ TRÊN ĐÂY phải khớp CHÍNH XÁC với địa chỉ bạn")
        print("        đã dán vào ô Add people trong Google Calendar.")
    else:
        print(f"\n[1] Không thấy {cfg.SERVICE_ACCOUNT_FILE} -> đang dùng OAuth")

    print(f"\n    CALENDAR_ID trong config.py: {cfg.CALENDAR_ID}")

    try:
        service = auth.get_calendar_service()
    except Exception as exc:
        print(f"\nKhông xác thực được: {exc}")
        return 1

    # ------------------------------------------------- 2. thấy được lịch nào
    print("\n[2] Những lịch service account nhìn thấy")
    try:
        resp = service.calendarList().list().execute()
        items = resp.get("items", [])
        if not items:
            print("    (TRỐNG)")
            print("\n    Danh sách trống nghĩa là CHƯA có lịch nào được share")
            print("    cho service account, hoặc lệnh share chưa có hiệu lực.")
        for it in items:
            print(f"    - {it.get('id')}")
            print(f"        tên     : {it.get('summary')}")
            print(f"        quyền   : {it.get('accessRole')}")
            if it.get("primary"):
                print("        (đây là lịch chính của service account, "
                      "không phải của bạn)")
    except Exception as exc:
        print(f"    Lỗi: {exc}")

    # ------------------------------------------ 3. vào thẳng CALENDAR_ID
    print(f"\n[3] Thử truy cập trực tiếp {cfg.CALENDAR_ID}")
    try:
        cal = service.calendars().get(calendarId=cfg.CALENDAR_ID).execute()
        print(f"    OK. Tên lịch: {cal.get('summary')}")
        print(f"    Múi giờ    : {cal.get('timeZone')}")
        print("\n    Quyền đã thông. Chạy lại: python run.py check")
        return 0
    except Exception as exc:
        code = getattr(getattr(exc, "resp", None), "status", None)
        print(f"    Thất bại (HTTP {code})")

    # ------------------------------------------------------------ kết luận
    print("\n" + "=" * 62)
    print("  CẦN KIỂM TRA, theo thứ tự khả năng cao nhất")
    print("=" * 62)
    print("""
  a) Bấm Send chưa?
     Dán email vào ô rồi mà quên bấm nút Send thì không có gì
     được lưu cả. Đây là lỗi phổ biến nhất.

  b) Share đúng lịch chưa?
     Phải là lịch nằm trong mục "My calendars", thường mang TÊN BẠN
     hoặc chính địa chỉ Gmail. Không phải "Birthdays", "Holidays in
     Vietnam", hay lịch phụ nào khác.

  c) Đang đăng nhập bằng tài khoản Google nào?
     Nếu trình duyệt có nhiều tài khoản, kiểm tra avatar góc trên
     phải của Google Calendar có đúng tài khoản trong CALENDAR_ID
     không. Share nhầm từ tài khoản khác là chuyện rất hay xảy ra.

  d) Email service account có gõ sai không?
     So từng ký tự với địa chỉ ở mục [1] phía trên. Dán, đừng gõ tay.

  e) Đợi thêm 1-2 phút.
     Thường có hiệu lực ngay, nhưng thỉnh thoảng trễ.
""")
    return 1


if __name__ == "__main__":
    sys.exit(main())