"""
Kiểm thử Tầng 4.

    python tests/test_llm.py

Không gọi API thật. Dùng LLM giả để kiểm tra đúng thứ cần kiểm tra:
CODE có chặn được đầu ra tồi của mô hình hay không.

Đây là điểm mấu chốt của cả tầng này. Ta không test xem mô hình có thông
minh không — ta test xem khi nó đưa ra thứ nguy hiểm hoặc vô lý thì hệ
thống có đứng vững không.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ask
import config as cfg
import llm
import nlu
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


# Giữ bản gốc để khôi phục. Không có dòng này, các mục sau sẽ gọi vào
# hàm giả do mục trước cài đặt — và test sẽ báo lỗi ở chỗ không có lỗi.
REAL_COMPLETE = llm.complete
REAL_COMPLETE_JSON = llm.complete_json
REAL_GEMINI_CALL = llm._gemini_call
REAL_GEMINI_DISCOVER = llm._gemini_discover
REAL_CANDIDATES = list(llm.GEMINI_CANDIDATES)


def fake_llm(payload):
    """Thay hàm gọi API bằng một hằng số."""
    llm.complete_json = lambda s, u, max_tokens=0: payload
    llm.complete = lambda s, u, max_tokens=0: "câu trả lời giả"


def restore_llm():
    """
    Khôi phục MỌI thứ đã bị thay bằng bản giả.

    Thiếu một dòng ở đây là các mục sau báo lỗi ở chỗ không có lỗi — đúng
    như đã xảy ra hai lần khi viết bộ test này.
    """
    llm.complete = REAL_COMPLETE
    llm.complete_json = REAL_COMPLETE_JSON
    llm._gemini_call = REAL_GEMINI_CALL
    llm._gemini_discover = REAL_GEMINI_DISCOVER
    llm.GEMINI_CANDIDATES = list(REAL_CANDIDATES)
    llm._GEMINI_MODEL = None


def main():
    print("\n--- 1. Bóc JSON khỏi vỏ markdown ---")
    import json as _json
    real_complete = llm.complete
    for raw, desc in [
        ('{"a": 1}', "JSON trần"),
        ('```json\n{"a": 1}\n```', "bọc ```json"),
        ('```\n{"a": 1}\n```', "bọc ```"),
        ('Đây là kết quả:\n{"a": 1}\nHy vọng giúp ích!', "có lời dẫn"),
    ]:
        llm.complete = lambda s, u, max_tokens=0, _r=raw: _r
        try:
            check(desc, llm.complete_json("", "") == {"a": 1})
        except Exception as e:
            check(desc, False, str(e))
    llm.complete = lambda s, u, max_tokens=0: "không phải json gì cả"
    try:
        llm.complete_json("", "")
        check("rác -> ném lỗi", False, "không ném")
    except ValueError:
        check("rác -> ném lỗi", True)
    llm.complete = real_complete

    print("\n--- 2. Rào chắn SQL: chặn câu nguy hiểm ---")
    danger = [
        ("DELETE FROM tasks", "DELETE"),
        ("DROP TABLE events", "DROP"),
        ("UPDATE tasks SET status='done'", "UPDATE"),
        ("INSERT INTO tasks VALUES (1)", "INSERT"),
        ("SELECT 1; DELETE FROM tasks", "hai câu lệnh"),
        ("PRAGMA table_info(tasks)", "PRAGMA"),
        ("ATTACH DATABASE '/x' AS y", "ATTACH"),
        ("SELECT load_extension('evil')", "load_extension"),
        ("", "rỗng"),
    ]
    for sql, desc in danger:
        ok, _ = ask.validate_sql(sql)
        check(f"chặn {desc}", not ok, f"lọt: {sql[:40]}")

    print("\n--- 3. Rào chắn SQL: cho qua câu hợp lệ ---")
    good = [
        "SELECT * FROM tasks LIMIT 10",
        "select title, est_min from tasks where status='open' limit 5",
        "WITH x AS (SELECT 1 AS n) SELECT n FROM x LIMIT 1",
        "SELECT COUNT(*) FROM action_log WHERE executed=0 LIMIT 1",
    ]
    for sql in good:
        ok, _ = ask.validate_sql(sql)
        check(f"cho qua: {sql[:38]}", ok)

    print("\n--- 4. Kết nối chỉ đọc thật sự chặn ghi ---")
    db = "test_ro.db"
    if os.path.exists(db):
        os.remove(db)
    conn = store.connect(db)
    T.add(conn, "Việc thử", 60)
    conn.close()

    cols, rows = ask.run_readonly("SELECT title FROM tasks LIMIT 5", db)
    check("đọc được dữ liệu", len(rows) == 1 and rows[0][0] == "Việc thử",
          f"{rows}")

    import sqlite3
    try:
        ask.run_readonly("DELETE FROM tasks", db)
        check("driver chặn ghi", False, "xoá được — RẤT NGUY HIỂM")
    except sqlite3.Error:
        check("driver chặn ghi", True)

    conn = store.connect(db)
    check("dữ liệu còn nguyên", len(T.open_tasks(conn)) == 1)
    conn.close()
    os.remove(db)

    print("\n--- 5. NLU: trích task từ câu tự nhiên ---")
    fake_llm({"title": "Nộp báo cáo thực tập", "est_min": 240,
              "due": "31/12/2026", "note": "hiểu rồi"})
    r = nlu.parse_task("mai phải nộp báo cáo thực tập, chắc mất 4 tiếng")
    check("lấy đúng tên", r["title"] == "Nộp báo cáo thực tập")
    check("lấy đúng ước tính", r["est_min"] == 240)
    check("có hạn chót", r["due_ts"] is not None)
    check("không cảnh báo thừa", r["warnings"] == [], f"{r['warnings']}")

    print("\n--- 6. NLU: chặn đầu ra vô lý của mô hình ---")
    fake_llm({"title": "Việc gì đó", "est_min": 999999, "due": None})
    r = nlu.parse_task("x")
    check("hạ ước tính điên rồ", r["est_min"] <= nlu.MAX_EST_MIN, f"{r['est_min']}")
    check("có báo cho người dùng biết", len(r["warnings"]) > 0)

    fake_llm({"title": "Việc gì đó", "est_min": None, "due": "ngày nào đó"})
    r = nlu.parse_task("x")
    check("thiếu ước tính -> mặc định 1h", r["est_min"] == 60)
    check("hạn không hiểu -> bỏ qua", r["due_ts"] is None)
    check("có cảnh báo về hạn",
          any("hạn" in w for w in r["warnings"]), f"{r['warnings']}")

    fake_llm({"title": "", "est_min": 60, "due": None})
    try:
        nlu.parse_task("x")
        check("tên rỗng -> ném lỗi", False, "không ném")
    except ValueError:
        check("tên rỗng -> ném lỗi", True)

    fake_llm({"title": "A" * 300, "est_min": 60, "due": None})
    r = nlu.parse_task("x")
    check("tên quá dài -> cắt", len(r["title"]) <= 120)

    print("\n--- 7. ask(): từ chối SQL nguy hiểm do mô hình sinh ---")
    llm.complete_json = lambda s, u, max_tokens=0: {
        "sql": "DELETE FROM tasks", "intent": "xoá hết"}
    try:
        ask.ask("xoá hết việc đi")
        check("chặn SQL phá hoại từ mô hình", False, "không chặn")
    except ValueError as e:
        check("chặn SQL phá hoại từ mô hình", "không an toàn" in str(e))

    restore_llm()

    print("\n--- 8. Chọn nhà cung cấp ---")
    saved = {k: os.environ.pop(k, None)
             for k in ("LLM_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY")}
    llm._ollama_up = lambda: False

    check("không có gì -> rỗng", llm.provider() == "", llm.provider())
    check("available() = False", llm.available() is False)

    os.environ["ANTHROPIC_API_KEY"] = "x"
    check("chỉ có anthropic -> anthropic", llm.provider() == "anthropic")

    os.environ["GEMINI_API_KEY"] = "y"
    check("có cả hai -> ưu tiên gemini (miễn phí)",
          llm.provider() == "gemini", llm.provider())

    os.environ["LLM_PROVIDER"] = "ollama"
    check("LLM_PROVIDER ép được", llm.provider() == "ollama")
    del os.environ["LLM_PROVIDER"]

    llm._ollama_up = lambda: True
    del os.environ["GEMINI_API_KEY"]
    del os.environ["ANTHROPIC_API_KEY"]
    check("chỉ có ollama -> ollama", llm.provider() == "ollama")

    llm._ollama_up = lambda: False
    try:
        llm.complete("a", "b")
        check("chưa cấu hình -> ném NotAvailable", False, "không ném")
    except llm.NotAvailable as e:
        check("chưa cấu hình -> ném NotAvailable",
              "Gemini" in str(e) and "MIỄN PHÍ" in str(e))

    print("\n--- 9. Gemini: bóc text và xử lý lỗi ---")
    check("bóc được text",
          llm._gemini_text({"candidates": [{"content": {"parts": [
              {"text": "xin "}, {"text": "chào"}]}}]}) == "xin chào")
    try:
        llm._gemini_text({"promptFeedback": {"blockReason": "SAFETY"}})
        check("không có candidates -> ném lỗi", False, "không ném")
    except RuntimeError as e:
        check("không có candidates -> ném lỗi", "SAFETY" in str(e))

    os.environ["GEMINI_API_KEY"] = "y"
    os.environ["LLM_PROVIDER"] = "gemini"

    class FakeResp:
        def __init__(self, code, body=None):
            self.status_code = code
            self.text = "loi"
            self._b = body or {}
        def json(self):
            return self._b

    llm._gemini_call = lambda m, s, u, n: FakeResp(429)
    try:
        llm.complete("a", "b")
        check("429 -> báo vượt hạn mức", False, "không ném")
    except RuntimeError as e:
        check("429 -> báo vượt hạn mức", "hạn mức" in str(e))

    llm._gemini_call = lambda m, s, u, n: FakeResp(403)
    try:
        llm.complete("a", "b")
        check("403 -> báo key sai", False, "không ném")
    except llm.NotAvailable as e:
        check("403 -> báo key sai", "từ chối" in str(e))

    calls = []
    def fake_call(m, s, u, n):
        calls.append(m)
        if m == "gemini-2.5-flash":
            return FakeResp(404)
        return FakeResp(200, {"candidates": [{"content":
                                              {"parts": [{"text": "ok"}]}}]})
    llm._gemini_call = fake_call
    llm._GEMINI_MODEL = None
    check("tên model hỏng -> tự thử tên khác",
          llm.complete("a", "b") == "ok", f"đã thử: {calls}")
    check("nhớ lại model dùng được", llm._GEMINI_MODEL is not None)

    print("\n--- 10. Tự đi theo gợi ý model của Google ---")
    # Đây là lỗi thật gặp phải: gemini-2.5-flash bị gỡ, và Google ghi luôn
    # tên thay thế trong thông báo lỗi. Code phải đọc được gợi ý đó.
    GOOGLE_404 = ('{"error":{"code":404,"message":"This model '
                  'models/gemini-2.5-flash is no longer available to new '
                  'users. Please update your code to use '
                  'models/gemini-3.6-flash for the latest features."}}')

    check("bóc đúng tên được gợi ý",
          llm._suggested_model(GOOGLE_404, {"gemini-2.5-flash"})
          == "gemini-3.6-flash")
    check("không gợi lại tên vừa hỏng",
          llm._suggested_model(GOOGLE_404,
                               {"gemini-2.5-flash", "gemini-3.6-flash"}) is None)

    seen = []
    class R404:
        status_code = 404
        text = GOOGLE_404
        def json(self): return {}
    class R200:
        status_code = 200
        text = "ok"
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "Hà Nội"}]}}]}

    def call(m, s_, u, n, retries=2):
        seen.append(m)
        return R200() if m == "gemini-3.6-flash" else R404()

    llm._gemini_call = call
    llm._GEMINI_MODEL = None
    llm.GEMINI_CANDIDATES = ["gemini-2.5-flash"]
    check("đi theo gợi ý và gọi được", llm.complete("a", "b") == "Hà Nội",
          f"đã thử: {seen}")
    check("chỉ tốn 2 lần gọi", len(seen) == 2, f"{seen}")
    check("nhớ tên mới", llm._GEMINI_MODEL == "gemini-3.6-flash")

    print("\n--- 11. Hết cách -> báo đầy đủ, không im lặng ---")
    llm._gemini_call = lambda m, s_, u, n, retries=2: R404()
    llm._gemini_discover = lambda: None
    llm._GEMINI_MODEL = None
    llm.GEMINI_CANDIDATES = ["a-model", "b-model"]
    try:
        llm.complete("a", "b")
        check("ném lỗi khi hết cách", False, "không ném")
    except RuntimeError as e:
        check("ném lỗi khi hết cách", True)
        check("liệt kê mọi tên đã thử",
              "a-model" in str(e) and "b-model" in str(e), str(e)[:200])
        check("chỉ cách ép tên thủ công", "GEMINI_MODEL" in str(e))

    print("\n--- 12. Hết token: báo đúng bệnh thay vì lỗi khó hiểu ---")
    # Lỗi thật gặp phải: Gemini 3.x tiêu token cho suy luận nội bộ trước
    # khi viết. Ngân sách thấp -> HTTP 200 nhưng nội dung là mảnh vụn.
    try:
        llm._gemini_text({"candidates": [
            {"content": {"parts": []}, "finishReason": "MAX_TOKENS"}]})
        check("rỗng vì hết token -> báo rõ", False, "không ném")
    except RuntimeError as e:
        check("rỗng vì hết token -> báo rõ", "token" in str(e))

    try:
        llm._gemini_text({"candidates": [
            {"content": {"parts": [{"text": ', "đầu tuần" = Thứ hai kế'}]},
             "finishReason": "MAX_TOKENS"}]})
        check("bị cắt giữa chừng -> báo rõ", False, "không ném")
    except RuntimeError as e:
        check("bị cắt giữa chừng -> báo rõ", "cắt giữa chừng" in str(e))

    check("bình thường thì trả text",
          llm._gemini_text({"candidates": [
              {"content": {"parts": [{"text": "ok"}]},
               "finishReason": "STOP"}]}) == "ok")

    llm.complete = lambda s_, u, max_tokens=0: ', "đầu tuần" = Thứ hai kế'
    try:
        llm.complete_json("s", "u")
        check("JSON hỏng -> in nguyên văn", False, "không ném")
    except ValueError as e:
        check("JSON hỏng -> in nguyên văn", "Nguyên văn" in str(e))
        check("gợi ý cách chữa", "GEMINI_MIN_TOKENS" in str(e))
    restore_llm()

    restore_llm()

    print("\n--- 13. Lỗi tạm thời phía Google ---")
    OK_BODY = {"candidates": [{"content": {"parts": [{"text": "ok"}]},
                               "finishReason": "STOP"}]}

    class Rx:
        def __init__(self, code, body=None, text=""):
            self.status_code, self._b, self.text = code, body or {}, text
        def json(self):
            return self._b

    # 503 = Google quá tải. Phải thử lại CHÍNH model đó, không bỏ đi thử
    # tên khác — rất có thể nó vẫn là tên đúng, chỉ là máy chủ đang nghẽn.
    n = {"c": 0}
    def post_503(m, s_, u, t, no_think=True):
        n["c"] += 1
        return Rx(200, OK_BODY) if n["c"] >= 3 else Rx(503, text="high demand")
    llm._gemini_post = post_503
    r = llm._gemini_call("m", "s", "u", 100, retries=4)
    check("503 -> thử lại rồi thành công", r.status_code == 200)
    check("thử lại đúng 3 lần", n["c"] == 3, f"{n['c']}")

    # 400 do thinkingConfig: Gemini 3.x không cho tắt suy luận nội bộ,
    # và chỉ báo cụt lủn "invalid argument" chứ không nhắc chữ nào.
    seen = []
    def post_400(m, s_, u, t, no_think=True):
        seen.append(no_think)
        return (Rx(400, text="Request contains an invalid argument.")
                if no_think else Rx(200, OK_BODY))
    llm._gemini_post = post_400
    r = llm._gemini_call("m", "s", "u", 100, retries=3)
    check("400 -> tự bỏ thinkingConfig", r.status_code == 200)
    check("gọi lại đúng một lần không kèm", seen == [True, False], f"{seen}")

    print("\n--- 14. Nhớ tên model sang lần chạy sau ---")
    import os as _os
    llm._gemini_post = lambda m, s_, u, t, no_think=True: Rx(200, OK_BODY)
    llm.GEMINI_CANDIDATES = ["gemini-flash-latest"]
    llm._GEMINI_MODEL = None
    llm._save_cached_model("")
    llm.complete("s", "u")
    check("lưu lại tên dùng được", bool(llm._load_cached_model()))
    llm._GEMINI_MODEL = None
    check("describe() đọc được từ cache",
          "tự dò" not in llm.describe(), llm.describe())
    try:
        _os.remove(llm._CACHE_FILE)
    except OSError:
        pass

    llm._GEMINI_MODEL = None
    for k, v in saved.items():
        os.environ.pop(k, None)
        if v:
            os.environ[k] = v

    print(f"\n{'=' * 46}")
    print(f"  {PASS} PASS, {FAIL} FAIL")
    print(f"{'=' * 46}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())