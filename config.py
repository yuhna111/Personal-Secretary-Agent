"""
Cấu hình agent. Sửa file này trước khi chạy.
"""

import os

# ---------------------------------------------------------------- Lịch
# Với SERVICE ACCOUNT: điền chính địa chỉ Gmail của bạn.
#   ("primary" sẽ trỏ vào lịch trống của service account, không phải lịch bạn.)
# Với OAUTH: để "primary" cũng được.
CALENDAR_ID = "yuhna0811@gmail.com"

TIMEZONE = "Asia/Ho_Chi_Minh"

# ---------------------------------------------------------------- Xác thực
# Để "auto": tự dò service_account.json trước, rồi mới tới credentials.json.
# Ép cứng bằng "service_account" hoặc "oauth".
AUTH_BACKEND = "auto"

SERVICE_ACCOUNT_FILE = "service_account.json"
OAUTH_CLIENT_FILE = "credentials.json"
OAUTH_TOKEN_FILE = "token.json"          # tự sinh sau lần đăng nhập đầu

# Giai đoạn shadow mode chỉ cần readonly. Khi bật quyền ghi, đổi sang:
#   "https://www.googleapis.com/auth/calendar.events"
# và nhớ nâng quyền chia sẻ lịch cho service account lên "Make changes to events".
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

# ---------------------------------------------------------------- An toàn
# SHADOW MODE: agent tính toán và ghi log mọi thứ nó ĐỊNH làm, nhưng không
# thực sự ghi lên lịch. Chạy ít nhất 3-4 tuần trước khi tắt.
SHADOW_MODE = True

# Trần số thao tác ghi mỗi ngày. Vượt là agent dừng và báo cho bạn.
# Đây là cầu dao chống vòng lặp hỏng, không phải giới hạn hiệu năng.
MAX_WRITES_PER_DAY = 20

# Không hành động ghi trong khung giờ này (giờ địa phương).
# Sáng dậy thấy 4 thay đổi lạ trên lịch là mất niềm tin ngay lập tức.
QUIET_HOURS = (22, 7)

# ---------------------------------------------------------------- Sync
DB_PATH = "agent.db"
POLL_SECONDS = 90

# Lần full sync đầu tiên chỉ kéo về cửa sổ này, đừng kéo 10 năm lịch sử.
SYNC_PAST_DAYS = 7
SYNC_FUTURE_DAYS = 60

# ---------------------------------------------------------------- Nhãn agent
# Mọi sự kiện agent tạo đều mang nhãn này trong extendedProperties.private.
# Nhờ đó agent nhận ra thay đổi nào là do chính nó gây ra và bỏ qua,
# tránh vòng lặp tự kích hoạt.
AGENT_TAG = "agent"
AGENT_VERSION = "v1"

# ---------------------------------------------------------------- Lập kế hoạch
# Khung giờ agent được phép xếp việc cho bạn (giờ địa phương).
# Ngoài khung này nó sẽ không bao giờ đề xuất gì.
WORK_HOURS = (8, 22)

# Block ngắn hơn mức này thì vô dụng -> bỏ qua chỗ trống đó.
MIN_BLOCK_MIN = 30

# Không đề xuất block dài hơn mức này. Việc 4 tiếng sẽ bị chia nhỏ.
MAX_BLOCK_MIN = 120

# Khoảng đệm trước và sau mỗi sự kiện đã có. Bạn không dịch chuyển
# tức thời từ cuộc họp sang bàn học.
BUFFER_MIN = 15

# Số ngày nhìn tới khi kiểm tra tính khả thi.
HORIZON_DAYS = 14

# Tiền tố nhận diện lệnh nhập việc từ Google Calendar.
#   @task Viết báo cáo | 240 | 30/8
TASK_PREFIX = "@task"

# ---------------------------------------------------------------- Email
# Dùng để gửi bản tóm tắt buổi sáng tới điện thoại bạn.
#
# KHÔNG dùng mật khẩu Gmail thường. Phải tạo App Password:
#   1. Bật xác thực 2 bước: myaccount.google.com/security
#   2. Tạo App Password : myaccount.google.com/apppasswords
#   3. Dán chuỗi 16 ký tự vào đây (khoảng trắng bỏ hay giữ đều được)
SMTP_USER = "yuhna0811@gmail.com"
SMTP_APP_PASSWORD = "qfqb lmti yxil cere"

# Để trống thì gửi cho chính SMTP_USER.
NOTIFY_TO = ""

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
