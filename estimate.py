"""
TẦNG 6 — Học thói quen ước tính.

Câu hỏi: bạn nghĩ 60 phút, thực tế mất bao nhiêu?

Đây là ý tưởng gốc từ đầu dự án, quay lại dưới dạng một cảm biến của agent
thay vì một sản phẩm riêng. Google Calendar không bao giờ trả lời được câu
này vì nó không bao giờ hỏi thực tế đã xảy ra thế nào.

Bốn quyết định thống kê, giống hệt lý do đã dùng ở nơi khác trong dự án:

1. Mô hình log(tỉ lệ), không mô hình tỉ lệ.
   Tỉ lệ lệch phải: không âm, đuôi dài. Vượt gấp đôi (2.0) và xong trong
   nửa thời gian (0.5) phải đối xứng nhau — trên thang log thì đúng vậy,
   trên thang thường thì không.

2. Co về 1.0 khi ít dữ liệu.
   Cùng một công thức chạy từ mẫu thứ nhất tới mẫu thứ trăm. Không cần
   "chế độ chưa đủ dữ liệu" riêng.

3. Cắt đuôi trên.
   Một việc ước tính 30 phút mà mất 5 tiếng không được phép định đoạt
   toàn bộ hệ số.

4. Không dùng mạng nơ-ron.
   n cỡ vài chục, quan hệ gần như tuyến tính, và bắt buộc phải giải
   thích được.
"""

import math

import tasks as T

# Số mẫu tối thiểu để ước lượng cá nhân bắt đầu tách khỏi giá trị mặc định
MIN_SAMPLES = 5

# Prior "nặng" tương đương bao nhiêu quan sát thật.
# Cao thì hệ số nhích chậm nhưng ổn định; thấp thì nhạy nhưng dễ nhiễu.
PRIOR_STRENGTH = 3.0

# Cắt tỉ lệ ở hai đầu trước khi tính. Ngoài khoảng này gần như chắc chắn
# là ghi nhầm hoặc bỏ dở, không phải sai lệch ước tính thật.
CLAMP = (0.2, 5.0)


def samples(conn):
    """
    Các cặp (ước tính, thực tế) dùng được.

    Chỉ lấy việc ĐÃ ĐÓNG: việc đang làm dở thì chưa biết cuối cùng mất
    bao lâu, nên chưa so được.
    """
    rows = conn.execute(
        "SELECT * FROM tasks WHERE status='done' "
        "AND est_min > 0 AND COALESCE(done_min,0) > 0 ORDER BY id"
    ).fetchall()
    out = []
    for r in rows:
        ratio = float(r["done_min"]) / float(r["est_min"])
        out.append({
            "id": r["id"], "title": r["title"],
            "est": float(r["est_min"]), "done": float(r["done_min"]),
            "ratio": ratio,
            "clamped": not (CLAMP[0] <= ratio <= CLAMP[1]),
        })
    return out


def _clamp(x):
    return min(max(x, CLAMP[0]), CLAMP[1])


def analyze(conn):
    """
    Trả về dict mô tả độ chính xác ước tính.

    factor = hệ số nhân. 1.4 nghĩa là việc bạn nghĩ 60 phút thực tế mất 84.
    """
    s = samples(conn)
    n = len(s)

    if n == 0:
        return {"n": 0, "factor": 1.0, "samples": [], "warnings": [],
                "spread": None, "confident": False}

    logs = [math.log(_clamp(x["ratio"])) for x in s]

    # Co về 1.0 (log = 0). Prior yếu dần khi n tăng, không cần rẽ nhánh.
    mu = sum(logs) / (n + PRIOR_STRENGTH)

    if n >= 2:
        m = sum(logs) / n
        var = sum((x - m) ** 2 for x in logs) / n
        sigma = math.sqrt(var)
    else:
        sigma = 0.0

    warnings = _sanity(s)

    return {
        "n": n,
        "factor": math.exp(mu),
        "raw_factor": math.exp(sum(logs) / n),
        "spread": (math.exp(mu - sigma), math.exp(mu + sigma)) if n >= 2 else None,
        "samples": s,
        "warnings": warnings,
        "confident": n >= MIN_SAMPLES and not warnings,
    }


def _sanity(s):
    """
    Kiểm tra dữ liệu có đáng tin không.

    Quan trọng ngang phép tính. Một hệ số tính từ dữ liệu hỏng còn tệ hơn
    không có hệ số nào, vì nó trông như thông tin.
    """
    w = []
    n = len(s)

    exact = sum(1 for x in s if abs(x["ratio"] - 1.0) < 0.02)
    if n >= 3 and exact / n > 0.6:
        w.append(
            f"{exact}/{n} việc có tỉ lệ đúng bằng 1.00. Gần như chắc chắn "
            "chúng được ghi từ bản cũ — bản đó tự đóng việc khi done_min "
            "chạm est_min, nên tỉ lệ bị chặn cứng ở 1.0. Những mẫu này "
            "KHÔNG phản ánh thực tế."
        )

    low = sum(1 for x in s if x["ratio"] < 0.4)
    if low and low / n > 0.3:
        w.append(
            f"{low}/{n} việc đóng khi mới làm dưới 40% ước tính. Có thể bạn "
            "xong sớm thật, cũng có thể bạn bỏ dở — hai chuyện đó khác nhau "
            "nhưng dữ liệu không phân biệt được."
        )

    if any(x["clamped"] for x in s):
        k = sum(1 for x in s if x["clamped"])
        w.append(f"{k} việc có tỉ lệ ngoài khoảng {CLAMP} nên đã bị cắt bớt "
                 "khi tính.")

    return w


def apply_factor(conn, est_min):
    """Hiệu chỉnh một ước tính mới bằng hệ số đã học."""
    a = analyze(conn)
    return est_min * a["factor"], a