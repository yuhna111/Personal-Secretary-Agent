"""
Sinh file .ics từ thời khoá biểu PTIT để nhập vào Google Calendar.

    python tools/make_schedule.py

Vì sao .ics chứ không phải .csv: bản nhập CSV của Google KHÔNG hỗ trợ lịch
lặp. Sáu môn học suốt một kỳ sẽ thành hàng trăm sự kiện rời rạc, sửa một
buổi phải sửa từng cái. File .ics có RRULE nên mỗi môn chỉ là một sự kiện
lặp hàng tuần.

SỬA HAI DÒNG NGÀY THÁNG BÊN DƯỚI TRƯỚC KHI CHẠY.
"""

import os
from datetime import datetime, timedelta

# ---------------------------------------------------------------- CẦN SỬA
# Ngày thứ Hai của tuần đầu tiên có lịch học như dưới đây.
# Ảnh chụp là Tuần 5 (07/09 - 13/09). Nếu học kỳ đã bắt đầu từ trước và
# lịch giống nhau, lùi ngày này về tuần đầu tiên của kỳ.
WEEK_MONDAY = "2026-09-07"

# Ngày cuối cùng còn học (hết học kỳ 1).
SEMESTER_END = "2027-03-15"

# Xuất ra thư mục gốc dự án, không phải cạnh script.
OUT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "lich-hoc.ics")

# ---------------------------------------------------------------- Lịch học
# (thứ, giờ bắt đầu, giờ kết thúc, tên môn, phòng, giảng viên)
# thứ: 0 = Thứ Hai ... 6 = Chủ Nhật
CLASSES = [
    # --- Thứ Ba ---
    (1, "13:00", "15:50", "Nhập môn Khoa học Dữ liệu (INT14120_CLC)",
     "502-A1 (HN)", "Nguyễn Tất Thắng"),
    (1, "16:00", "18:50", "Học máy (INT14121_CLC)",
     "502-A1 (HN)", "Nguyễn Xuân Đức"),

    # --- Thứ Tư ---
    (2, "10:00", "11:50", "Phát triển ứng dụng thiết bị di động (INT1449_CLC)",
     "802-A2 (HN)", "Đào Ngọc Phong"),
    (2, "13:00", "15:50", "Tư tưởng Hồ Chí Minh (BAS1122)",
     "502-A1 (HN)", "Đào Mạnh Ninh"),

    # --- Thứ Năm ---
    (3, "13:00", "15:50", "Xử lý ảnh (INT14123_CLC)",
     "502-A1 (HN)", "Phạm Văn Cường"),
    (3, "16:00", "18:50", "Phân tích và thiết kế HTTT (INT1342_CLC)",
     "502-A1 (HN)", "Trần Đình Quế"),
]

# Buổi dạy thêm — KHÔNG lặp hàng tuần, chỉ có ở một số tuần.
# Mỗi lần trường xếp thêm buổi mới, thêm một dòng vào đây rồi chạy lại
# script. Hoặc nhanh hơn: tạo thẳng trên Google Calendar, agent tự thấy
# qua vòng sync mà không cần đụng tới file này.
ONE_OFF = [
    ("2026-09-11", "16:00", "19:50",
     "Phát triển ứng dụng thiết bị di động (INT1449_CLC) - dạy thêm",
     "501-A3 (HN)", "Trịnh Thị Vân Anh"),
]

# ---------------------------------------------------------------- Bữa ăn
# Agent hiện xếp việc thẳng qua giờ ăn. Đặt False nếu không muốn.
ADD_MEALS = True
MEALS = [
    ("Ăn trưa", "12:00", "12:50", [0, 1, 2, 3, 4, 5, 6]),
    ("Ăn tối", "19:00", "19:45", [0, 1, 2, 3, 4, 5, 6]),
]


# ------------------------------------------------------------------ sinh ics
def esc(s):
    return s.replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;")


def stamp(date_str, time_str):
    d = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
    return d.strftime("%Y%m%dT%H%M%S")


def until_utc(date_str):
    # UNTIL phải ở UTC. VN là UTC+7, lấy 23:59 giờ VN -> 16:59 UTC.
    d = datetime.strptime(date_str, "%Y-%m-%d")
    return (d + timedelta(hours=16, minutes=59)).strftime("%Y%m%dT%H%M%SZ")


HEAD = """BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//agent thu ky//lich hoc//VI
CALSCALE:GREGORIAN
BEGIN:VTIMEZONE
TZID:Asia/Ho_Chi_Minh
BEGIN:STANDARD
DTSTART:19700101T000000
TZOFFSETFROM:+0700
TZOFFSETTO:+0700
TZNAME:+07
END:STANDARD
END:VTIMEZONE
"""


def event(uid, date_str, start, end, title, loc, desc, rrule=None):
    L = ["BEGIN:VEVENT",
         f"UID:{uid}@agent-thu-ky",
         f"DTSTAMP:{datetime.now().strftime('%Y%m%dT%H%M%S')}",
         f"DTSTART;TZID=Asia/Ho_Chi_Minh:{stamp(date_str, start)}",
         f"DTEND;TZID=Asia/Ho_Chi_Minh:{stamp(date_str, end)}",
         f"SUMMARY:{esc(title)}"]
    if loc:
        L.append(f"LOCATION:{esc(loc)}")
    if desc:
        L.append(f"DESCRIPTION:{esc(desc)}")
    if rrule:
        L.append(f"RRULE:{rrule}")
    L.append("END:VEVENT")
    return "\n".join(L)


def main():
    monday = datetime.strptime(WEEK_MONDAY, "%Y-%m-%d")
    until = until_utc(SEMESTER_END)
    out = [HEAD.rstrip()]
    n = 0

    for dow, start, end, title, room, gv in CLASSES:
        day = (monday + timedelta(days=dow)).strftime("%Y-%m-%d")
        n += 1
        out.append(event(
            f"class{n}", day, start, end, title, room,
            f"GV: {gv}", rrule=f"FREQ=WEEKLY;UNTIL={until}",
        ))

    for day, start, end, title, room, gv in ONE_OFF:
        n += 1
        out.append(event(f"once{n}", day, start, end, title, room, f"GV: {gv}"))

    if ADD_MEALS:
        for name, start, end, days in MEALS:
            n += 1
            day = (monday + timedelta(days=days[0])).strftime("%Y-%m-%d")
            byday = ",".join(["MO", "TU", "WE", "TH", "FR", "SA", "SU"][d]
                             for d in days)
            out.append(event(
                f"meal{n}", day, start, end, name, "", "",
                rrule=f"FREQ=WEEKLY;BYDAY={byday};UNTIL={until}",
            ))

    out.append("END:VCALENDAR")

    with open(OUT, "w", encoding="utf-8", newline="\r\n") as f:
        f.write("\n".join(out) + "\n")

    print(f"Đã tạo {os.path.basename(OUT)}")
    print(f"  {len(CLASSES)} môn lặp hàng tuần")
    print(f"  {len(ONE_OFF)} buổi dạy thêm (một lần)")
    if ADD_MEALS:
        print(f"  {len(MEALS)} bữa ăn lặp hàng ngày")
    print(f"  Từ {WEEK_MONDAY} đến {SEMESTER_END}")
    print("\nNhập vào Google Calendar:")
    print("  calendar.google.com > Settings > Import & export > Import")
    print("  Chọn file, và chọn đúng lịch yuhna0811@gmail.com")


if __name__ == "__main__":
    main()