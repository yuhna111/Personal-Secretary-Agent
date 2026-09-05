"""
Hiểu câu tiếng Việt tự nhiên thành task có cấu trúc.

    "mai phải nộp báo cáo thực tập, chắc mất 4 tiếng"
        -> {title: "Nộp báo cáo thực tập", est_min: 240, due: "31/08/2026"}

Nguyên tắc quan trọng: LLM CHỈ trích xuất, không quyết định gì.

Đầu ra của nó là JSON, và JSON đó bị code kiểm tra lại từ đầu bằng chính
T.parse_est / T.parse_due — cùng hàm dùng cho đường nhập tay. Nếu mô hình
bịa ra "est_min: 999999" hoặc một ngày vô lý, code chặn.

Đây là lý do LLM ngồi ở tầng này chứ không ngồi ở tầng lập kế hoạch: dịch
ngôn ngữ thì nó giỏi, và sai sót có thể kiểm tra được bằng luật.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import config as cfg
import llm
import tasks as T

MAX_EST_MIN = 60 * 40      # 40 tiếng cho một task là đã quá vô lý
MAX_DUE_DAYS = 365 * 2

SYSTEM = """Bạn trích xuất công việc từ câu tiếng Việt tự nhiên.

Trả về DUY NHẤT một object JSON, không lời dẫn, không markdown:
{
  "title":   "tên việc, viết gọn, hoa chữ đầu",
  "est_min": số phút ước tính (số nguyên) hoặc null nếu người dùng không nói,
  "due":     "dd/mm/yyyy" hoặc null nếu không có hạn,
  "note":    "một câu ngắn nói bạn đã hiểu gì, bằng tiếng Việt"
}

Quy tắc:
- "tiếng"/"giờ" = 60 phút. "buổi" = 180 phút.
- Không tự bịa ước tính nếu người dùng không nói. Để null.
- Ngày tương đối tính theo NGÀY HÔM NAY được cung cấp.
- "cuối tuần" = Chủ nhật tuần này. "đầu tuần sau" = Thứ hai kế tiếp.
- title không chứa thông tin thời gian.
"""


def _today_str():
    d = datetime.now(ZoneInfo(cfg.TIMEZONE))
    thu = ["Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu",
           "Thứ bảy", "Chủ nhật"][d.weekday()]
    return f"{thu}, {d:%d/%m/%Y}"


def parse_task(text):
    """
    Trả về dict(title, est_min, due_ts, note, warnings).
    Ném ValueError nếu không dùng được.
    """
    data = llm.complete_json(
        SYSTEM,
        f"HÔM NAY LÀ: {_today_str()}\n\nCÂU CỦA NGƯỜI DÙNG:\n{text}",
        max_tokens=400,
    )

    warnings = []

    title = str(data.get("title") or "").strip()
    if not title:
        raise ValueError("không trích được tên việc từ câu này")
    if len(title) > 120:
        title = title[:120]
        warnings.append("tên việc quá dài, đã cắt bớt")

    # --- ước tính: kiểm lại bằng chính hàm dùng cho nhập tay ---
    est = data.get("est_min")
    if est is None:
        est = 60.0
        warnings.append("không rõ ước tính, tạm để 1h")
    else:
        est = T.parse_est(str(est))
        if est is None or est <= 0:
            est = 60.0
            warnings.append("ước tính không hợp lệ, tạm để 1h")
        elif est > MAX_EST_MIN:
            warnings.append(
                f"ước tính {est / 60:.0f} tiếng nghe không hợp lý, "
                f"đã hạ xuống {MAX_EST_MIN / 60:.0f}h — nên chia nhỏ việc này"
            )
            est = float(MAX_EST_MIN)

    # --- hạn chót: cũng qua parser của code, không tin thẳng LLM ---
    due_ts = None
    if data.get("due"):
        due_ts = T.parse_due(str(data["due"]))
        if due_ts is None:
            warnings.append(f"không hiểu hạn '{data['due']}', bỏ qua")
        else:
            days = (due_ts - T.now_ts()) / 86400
            if days < -1:
                warnings.append(f"hạn {T.fmt_due(due_ts)} nằm trong quá khứ")
            elif days > MAX_DUE_DAYS:
                warnings.append("hạn quá xa, bỏ qua")
                due_ts = None

    return {
        "title": title,
        "est_min": est,
        "due_ts": due_ts,
        "note": str(data.get("note") or "").strip(),
        "warnings": warnings,
    }