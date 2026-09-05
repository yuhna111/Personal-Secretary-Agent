"""
Kiểm thử Tầng 6.

    python tests/test_estimate.py

Trọng tâm không phải "phép tính có đúng không" mà "hệ thống có NHẬN RA
dữ liệu hỏng không". Một hệ số tính từ dữ liệu hỏng còn tệ hơn không có
hệ số nào, vì nó trông như thông tin.
"""

import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import estimate as E
import store
import tasks as T

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        print(f"  FAIL  {name}  {detail}")


def make(conn, pairs):
    """pairs: list (est_min, done_min)"""
    for i, (e, d) in enumerate(pairs):
        tid = T.add(conn, f"Việc {i}", e)
        if d:
            T.log_progress(conn, tid, d)
        T.mark_done(conn, tid)


def main():
    print("\n--- 1. progress KHÔNG còn tự đóng việc ---")
    # Đây là lỗi gốc: bản cũ tự đóng khi done_min chạm est_min, nên
    # done_min không bao giờ vượt est_min và tỉ lệ bị chặn cứng ở 1.0.
    conn = store.connect(":memory:")
    tid = T.add(conn, "Viết báo cáo", 120)
    T.log_progress(conn, tid, 120)
    row = T.get(conn, tid)
    check("chạm ước tính vẫn còn mở", row["status"] == "open", row["status"])

    T.log_progress(conn, tid, 60)
    row = T.get(conn, tid)
    check("ghi vượt được ước tính", row["done_min"] == 180, row["done_min"])
    check("tính đúng phần vượt", T.over_estimate(row) == 60)
    check("vẫn chưa đóng", row["status"] == "open")

    T.mark_done(conn, tid)
    s = E.samples(conn)
    check("tỉ lệ vượt 1.0 được ghi nhận",
          abs(s[0]["ratio"] - 1.5) < 0.01, s[0]["ratio"])

    print("\n--- 2. Chưa có dữ liệu ---")
    conn = store.connect(":memory:")
    r = E.analyze(conn)
    check("n = 0", r["n"] == 0)
    check("hệ số mặc định 1.0", r["factor"] == 1.0)
    check("không tự tin", r["confident"] is False)

    print("\n--- 3. Việc đang làm dở KHÔNG được tính ---")
    conn = store.connect(":memory:")
    tid = T.add(conn, "Đang làm", 120)
    T.log_progress(conn, tid, 60)
    check("việc chưa đóng thì bỏ qua", len(E.samples(conn)) == 0,
          "chưa biết cuối cùng mất bao lâu thì chưa so được")

    print("\n--- 4. Co về 1.0 khi ít mẫu ---")
    conn = store.connect(":memory:")
    make(conn, [(60, 120)])                 # một mẫu, tỉ lệ 2.0
    r = E.analyze(conn)
    check("hệ số nằm giữa 1.0 và tỉ lệ thô",
          1.0 < r["factor"] < 2.0, f"{r['factor']:.2f}")
    check("tỉ lệ thô vẫn giữ để đối chiếu",
          abs(r["raw_factor"] - 2.0) < 0.01, r["raw_factor"])
    check("chưa đủ mẫu -> chưa tự tin", r["confident"] is False)

    print("\n--- 5. Nhiều mẫu nhất quán -> hệ số tiến về giá trị thật ---")
    conn = store.connect(":memory:")
    make(conn, [(60, 90)] * 12)             # đều đặn 1.5
    r = E.analyze(conn)
    check("hệ số tiến gần 1.5", 1.35 < r["factor"] < 1.5, f"{r['factor']:.2f}")
    check("đủ mẫu và sạch -> tự tin", r["confident"] is True, f"{r['warnings']}")
    lo, hi = r["spread"]
    check("dao động hẹp khi nhất quán", (hi - lo) < 0.2, f"{lo:.2f}-{hi:.2f}")

    print("\n--- 6. Một mẫu điên rồ không phá hỏng hệ số ---")
    conn = store.connect(":memory:")
    make(conn, [(60, 90)] * 10 + [(30, 1800)])   # 1 việc vượt 60 lần
    r = E.analyze(conn)
    check("hệ số vẫn quanh 1.5", 1.3 < r["factor"] < 1.9, f"{r['factor']:.2f}")
    check("có báo đã cắt bớt",
          any("cắt bớt" in w for w in r["warnings"]), r["warnings"])

    print("\n--- 7. PHÁT HIỆN dữ liệu hỏng: dồn đống ở đúng 1.00 ---")
    # Đúng tình huống thật: bản cũ tự đóng việc nên 4/5 mẫu bằng 1.00.
    conn = store.connect(":memory:")
    make(conn, [(240, 45), (120, 120), (240, 240), (60, 60), (180, 180)])
    r = E.analyze(conn)
    check("nhận ra bất thường", len(r["warnings"]) > 0)
    check("chỉ đúng nguyên nhân",
          any("chặn cứng ở 1.0" in w for w in r["warnings"]), r["warnings"])
    check("từ chối kết luận dù đủ số mẫu", r["confident"] is False,
          f"n={r['n']} nhưng dữ liệu không đáng tin")

    print("\n--- 8. Dữ liệu sạch cùng số mẫu thì KHÔNG cảnh báo ---")
    conn = store.connect(":memory:")
    make(conn, [(60, 75), (120, 155), (90, 100), (60, 80), (180, 210),
                (45, 50), (120, 130)])
    r = E.analyze(conn)
    check("không cảnh báo nhầm", r["warnings"] == [], r["warnings"])
    check("tự tin", r["confident"] is True)
    check("hệ số hợp lý", 1.1 < r["factor"] < 1.3, f"{r['factor']:.2f}")

    print("\n--- 9. Cảnh báo khi hay đóng việc quá sớm ---")
    conn = store.connect(":memory:")
    make(conn, [(120, 20), (120, 25), (60, 15), (120, 130), (60, 70)])
    r = E.analyze(conn)
    check("nhận ra nhiều việc đóng sớm",
          any("dưới 40%" in w for w in r["warnings"]), r["warnings"])

    print("\n--- 10. Đối xứng trên thang log ---")
    # Vượt gấp đôi (2.0) và xong trong nửa thời gian (0.5) phải triệt
    # tiêu nhau. Trên thang thường thì trung bình ra 1.25 — sai.
    conn = store.connect(":memory:")
    make(conn, [(60, 120), (60, 30)] * 6)
    r = E.analyze(conn)
    check("2.0 và 0.5 triệt tiêu nhau",
          abs(r["raw_factor"] - 1.0) < 0.01, f"{r['raw_factor']:.3f}")

    print("\n--- 11. apply_factor ---")
    conn = store.connect(":memory:")
    make(conn, [(60, 90)] * 12)
    adj, r = E.apply_factor(conn, 120)
    check("hiệu chỉnh ước tính mới", adj > 120, f"{adj:.0f}")
    check("đúng bằng est nhân hệ số",
          abs(adj - 120 * r["factor"]) < 0.01)

    print(f"\n{'=' * 46}")
    print(f"  {PASS} PASS, {FAIL} FAIL")
    print(f"{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())