"""
Hỏi đáp trên chính dữ liệu của bạn.

    "tuần này tôi đã dành bao nhiêu tiếng cho việc học?"
    "còn việc nào quá hạn không?"
    "agent đã đề xuất bao nhiêu block trong 7 ngày qua?"

Cách làm: LLM sinh câu SQL -> CODE kiểm tra lại -> chạy trên kết nối
CHỈ ĐỌC -> LLM diễn đạt kết quả bằng tiếng Việt.

Hai rào chắn, và cả hai đều cần thiết:

  1. Kiểm tra cú pháp (validate_sql)
     Chỉ cho phép SELECT/WITH, một câu lệnh duy nhất, cấm mọi từ khoá ghi.

  2. Kết nối chỉ đọc (mode=ro)
     Ngay cả khi rào thứ nhất bị lách, SQLite vẫn từ chối mọi thao tác ghi
     ở tầng driver.

Chỉ một rào là không đủ. Rào thứ nhất là danh sách đen — mà danh sách đen
thì luôn thiếu thứ gì đó. Rào thứ hai không dựa vào việc mình đoán đúng.
"""

import re
import sqlite3

import config as cfg
import llm

FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|replace|attach|detach|"
    r"pragma|vacuum|reindex|begin|commit|rollback|load_extension)\b",
    re.I,
)

SCHEMA_DOC = """
events        sự kiện trên lịch (bản sao cục bộ)
  id TEXT, summary TEXT, start_ts INT, end_ts INT  (unix epoch UTC)
  all_day INT, status TEXT, is_agent INT  (1 = do agent tạo)

tasks         công việc cần làm
  id INT, title TEXT, est_min REAL, done_min REAL
  due_ts INT (unix epoch, NULL nếu không hạn), hard INT
  status TEXT ('open' | 'done' | 'dropped'), created_ts INT
  source TEXT ('cli' | 'calendar')

action_log    mọi hành động agent đã làm hoặc đề xuất
  id INT, ts INT, op TEXT ('insert'|'patch'|'delete')
  event_id TEXT, reason TEXT
  executed INT  (0 = chỉ đề xuất trong shadow mode, 1 = đã ghi thật)
"""

SYSTEM_SQL = f"""Bạn viết câu SQL cho SQLite trả lời câu hỏi của người dùng.

SCHEMA:
{SCHEMA_DOC}

Quy tắc bắt buộc:
- CHỈ dùng SELECT. Tuyệt đối không INSERT/UPDATE/DELETE/DROP/PRAGMA.
- Một câu lệnh duy nhất, không dấu chấm phẩy ở cuối.
- Mọi cột *_ts là unix epoch UTC. Đổi sang giờ địa phương bằng
  datetime(ts, 'unixepoch', '+7 hours').
- Thời gian hiện tại: strftime('%s','now')
- Luôn có LIMIT, tối đa 50.
- Đặt alias tiếng Việt dễ đọc cho các cột tính toán.

Trả về DUY NHẤT JSON, không markdown:
{{"sql": "...", "intent": "một câu tiếng Việt nói bạn hiểu câu hỏi thế nào"}}
"""

SYSTEM_ANSWER = """Bạn diễn đạt kết quả truy vấn thành câu trả lời tiếng Việt.

- Ngắn gọn, 1-3 câu. Không lặp lại số liệu thô nếu đã rõ.
- Đổi phút sang dạng "3h30" khi hợp lý.
- Kết quả rỗng thì nói thẳng là không có dữ liệu nào khớp.
- Không bịa thêm thông tin ngoài bảng kết quả.
- Không mở đầu bằng "Dựa trên dữ liệu" hay tương tự. Trả lời thẳng.
"""


def validate_sql(sql):
    """Trả về (ok, lý_do)."""
    if not sql or not sql.strip():
        return False, "câu lệnh rỗng"

    s = sql.strip().rstrip(";").strip()

    if ";" in s:
        return False, "chứa nhiều câu lệnh"
    if not re.match(r"^\s*(select|with)\b", s, re.I):
        return False, "không phải câu SELECT"
    m = FORBIDDEN.search(s)
    if m:
        return False, f"chứa từ khoá bị cấm: {m.group(1)}"
    if len(s) > 4000:
        return False, "câu lệnh quá dài"

    return True, s


def run_readonly(sql, db_path=None):
    """Chạy SQL trên kết nối chỉ đọc. Trả về (cột, hàng)."""
    path = db_path or cfg.DB_PATH
    uri = f"file:{path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10)
    try:
        cur = conn.execute(sql)
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = cur.fetchmany(50)
        return cols, [list(r) for r in rows]
    finally:
        conn.close()


def _table(cols, rows, limit=20):
    if not cols:
        return "(không có cột)"
    out = [" | ".join(str(c) for c in cols)]
    for r in rows[:limit]:
        out.append(" | ".join("" if v is None else str(v) for v in r))
    if len(rows) > limit:
        out.append(f"... còn {len(rows) - limit} hàng")
    return "\n".join(out)


def ask(question, db_path=None, verbose=False):
    """
    Trả về dict(answer, sql, intent, cols, rows).
    Ném ValueError nếu SQL không qua được kiểm tra.
    """
    gen = llm.complete_json(SYSTEM_SQL, question, max_tokens=700)
    sql, intent = gen.get("sql", ""), gen.get("intent", "")

    ok, result = validate_sql(sql)
    if not ok:
        raise ValueError(f"SQL không an toàn ({result}): {sql[:200]}")
    sql = result

    if verbose:
        print(f"  [sql] {sql}")

    try:
        cols, rows = run_readonly(sql, db_path)
    except sqlite3.Error as exc:
        raise ValueError(f"SQL chạy lỗi: {exc}\n  {sql}")

    answer = llm.complete(
        SYSTEM_ANSWER,
        f"CÂU HỎI: {question}\n\nKẾT QUẢ:\n{_table(cols, rows)}",
        max_tokens=400,
    )

    return {"answer": answer.strip(), "sql": sql, "intent": intent,
            "cols": cols, "rows": rows}