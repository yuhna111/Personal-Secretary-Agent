"""
Lớp bọc LLM. File DUY NHẤT trong dự án gọi tới mô hình.

Ba nhà cung cấp, chọn bằng biến môi trường LLM_PROVIDER:

  gemini      MIỄN PHÍ. Google AI Studio, không cần thẻ tín dụng.
              Giới hạn ~15 request/phút — thừa cho dùng cá nhân.
              Key: aistudio.google.com/apikey  -> GEMINI_API_KEY

  ollama      MIỄN PHÍ, chạy trên máy bạn, dữ liệu không rời máy.
              Cần cài Ollama và tải model. Mô hình nhỏ sinh SQL kém hơn,
              nên lệnh `ask` sẽ hay bị rào chắn từ chối hơn.

  anthropic   Trả tiền theo lượt dùng. Chất lượng cao nhất cho việc
              sinh SQL và hiểu tiếng Việt.

Để trống LLM_PROVIDER thì tự dò: gemini -> anthropic -> ollama.

Vì sao dùng REST trực tiếp cho Gemini và Ollama thay vì SDK: bớt được
hai phụ thuộc, và `requests` thì dự án đã có sẵn.
"""

import json
import os
import re

DEFAULT_MAX_TOKENS = 1200

# Tên model Gemini đổi RẤT nhanh — bản 2.5 đã bị gỡ khỏi tay người dùng mới
# chỉ sau vài tháng. Nên ở đây có ba lớp phòng thủ, không chỉ một danh sách:
#   1. Thử lần lượt các tên đã biết
#   2. Đọc gợi ý Google nhét trong chính thông báo lỗi 404
#      ("Please update your code to use models/gemini-3.6-flash")
#   3. Gọi models.list hỏi thẳng xem hiện có gì
# Lớp 2 là lớp bền nhất: Google luôn nói tên thay thế khi gỡ một model.
GEMINI_CANDIDATES = ["gemini-flash-latest", "gemini-3.6-flash",
                     "gemini-2.5-flash", "gemini-2.0-flash"]
GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"

ANTHROPIC_MODEL = "claude-sonnet-4-6"
OLLAMA_URL = "http://localhost:11434"
OLLAMA_DEFAULT_MODEL = "qwen2.5:7b"

_CLIENT = None
_GEMINI_MODEL = None

# Nhớ tên model đã dùng được, để lần chạy sau đi thẳng thay vì dò lại từ
# đầu. Mỗi lần dò tốn 3-4 lời gọi API và vài giây — với đường truyền chập
# chờn thì đó là 3-4 cơ hội để hỏng.
_CACHE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           ".llm_model_cache")


def _load_cached_model():
    try:
        with open(_CACHE_FILE, encoding="utf-8") as f:
            return f.read().strip() or None
    except OSError:
        return None


def _save_cached_model(name):
    try:
        with open(_CACHE_FILE, "w", encoding="utf-8") as f:
            f.write(name or "")
    except OSError:
        pass          # cache hỏng không phải lý do để agent chết


class NotAvailable(Exception):
    pass


def _env(name):
    return os.environ.get(name, "").strip()


# ------------------------------------------------------------------ chọn nhà
def provider():
    p = _env("LLM_PROVIDER").lower()
    if p:
        return p
    if _env("GEMINI_API_KEY"):
        return "gemini"
    if _env("ANTHROPIC_API_KEY"):
        return "anthropic"
    if _ollama_up():
        return "ollama"
    return ""


def _ollama_up():
    try:
        import requests
        requests.get(f"{OLLAMA_URL}/api/tags", timeout=1.5)
        return True
    except Exception:
        return False


def available():
    p = provider()
    if p == "gemini":
        return bool(_env("GEMINI_API_KEY"))
    if p == "anthropic":
        return bool(_env("ANTHROPIC_API_KEY"))
    if p == "ollama":
        return _ollama_up()
    return False


PROBE_TOKENS = 400

# Model Gemini đời 3.x có bước suy luận nội bộ TRƯỚC khi viết câu trả lời,
# và bước đó cũng tiêu token. Đặt ngân sách thấp -> suy luận ăn hết, ta
# nhận HTTP 200 kèm nội dung rỗng hoặc mảnh vụn. Nên có sàn.
GEMINI_MIN_TOKENS = 2048


def describe():
    p = provider()
    if p == "gemini":
        return f"gemini ({_GEMINI_MODEL or _load_cached_model() or 'tự dò'})"
    if p == "anthropic":
        return f"anthropic ({ANTHROPIC_MODEL})"
    if p == "ollama":
        return f"ollama ({_env('OLLAMA_MODEL') or OLLAMA_DEFAULT_MODEL})"
    return "chưa cấu hình"


def setup_hint():
    return (
        "Chưa cấu hình LLM. Chọn một trong ba:\n\n"
        "  1. Gemini — MIỄN PHÍ, không cần thẻ tín dụng\n"
        "     Lấy key: https://aistudio.google.com/apikey\n"
        '     setx GEMINI_API_KEY "AIza..."\n\n'
        "  2. Ollama — miễn phí, chạy trên máy bạn\n"
        "     Cài từ ollama.com, rồi:  ollama pull qwen2.5:7b\n\n"
        "  3. Anthropic — trả phí, chất lượng cao nhất\n"
        '     setx ANTHROPIC_API_KEY "sk-ant-..."\n\n'
        "  Sau khi setx phải MỞ LẠI TERMINAL.\n"
        "  Không có LLM thì mọi lệnh khác vẫn chạy bình thường."
    )


# ------------------------------------------------------------------- gemini
def _gemini_call(model, system, user, max_tokens, retries=None):
    """
    Gọi Gemini, thử lại khi timeout.

    Đường từ VN tới generativelanguage.googleapis.com chập chờn thật:
    cùng một key, cùng một endpoint, lần trúng lần trượt. Nghỉ giãn dần
    giữa các lần thử (2s, 4s, 8s...) thay vì đâm liên tục — nếu là nghẽn
    tạm thời thì chờ có ích hơn là thử ngay.

    Nới thêm bằng:  setx LLM_RETRIES 6
    """
    import requests

    if retries is None:
        try:
            retries = int(_env("LLM_RETRIES") or 4)
        except ValueError:
            retries = 4

    no_think = True
    for attempt in range(retries + 1):
        try:
            r = _gemini_post(model, system, user, max_tokens, no_think)
        except (requests.exceptions.Timeout,
                requests.exceptions.ConnectionError):
            if attempt == retries:
                raise
            _wait(attempt, retries, "mạng chập chờn")
            continue

        # 400 với thinkingConfig: Gemini 3.x không cho tắt suy luận nội bộ.
        # Bỏ trường đó rồi gọi lại. Bản trước chỉ làm khi thông báo lỗi có
        # chữ "thinking", mà Google chỉ nói cụt lủn "invalid argument".
        if r.status_code == 400 and no_think:
            no_think = False
            continue

        # 5xx là quá tải TẠM THỜI ở phía Google. Phải thử lại CHÍNH model
        # này, đừng bỏ đi thử tên khác — rất có thể nó vẫn là tên đúng.
        if r.status_code in (500, 502, 503, 504) and attempt < retries:
            _wait(attempt, retries, f"Google báo {r.status_code}, đang quá tải")
            continue

        return r

    return r


def _wait(attempt, retries, why):
    import time
    wait = min(2 ** attempt, 8)
    print(f"  ({why}, thử lại {attempt + 2}/{retries + 1} sau {wait}s...)")
    time.sleep(wait)


def _gemini_post(model, system, user, max_tokens, no_think=True):
    import requests
    try:
        floor = int(_env("GEMINI_MIN_TOKENS") or GEMINI_MIN_TOKENS)
    except ValueError:
        floor = GEMINI_MIN_TOKENS
    gen = {"maxOutputTokens": max(max_tokens, floor),
           "temperature": 0}
    if no_think:
        # Tắt suy luận nội bộ: ta chỉ cần trích xuất và sinh SQL, không
        # cần model nghĩ lâu. Model cũ không hiểu trường này -> bắt 400
        # rồi gọi lại không kèm, thay vì chết cứng.
        gen["thinkingConfig"] = {"thinkingBudget": 0}

    r = requests.post(
        f"{GEMINI_BASE}/models/{model}:generateContent",
        headers={"x-goog-api-key": _env("GEMINI_API_KEY"),
                 "Content-Type": "application/json"},
        json={
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": gen,
        },
        # (thời gian chờ kết nối, thời gian chờ dữ liệu)
        timeout=(15, 120),
    )
    return r


def _gemini_discover():
    """Hỏi Google xem hiện có model nào dùng được, ưu tiên bản flash."""
    import requests
    r = requests.get(f"{GEMINI_BASE}/models",
                     headers={"x-goog-api-key": _env("GEMINI_API_KEY")},
                     timeout=30)
    r.raise_for_status()
    names = [
        m["name"].split("/")[-1]
        for m in r.json().get("models", [])
        if "generateContent" in (m.get("supportedGenerationMethods") or [])
    ]
    for n in names:
        if "flash" in n and "thinking" not in n and "image" not in n:
            return n
    return names[0] if names else None


SUGGEST_RE = re.compile(r"models/([A-Za-z0-9][A-Za-z0-9.\-]{2,40})")


def _suggested_model(text, tried):
    """
    Khi gỡ một model, Google ghi luôn tên thay thế trong thông báo lỗi:
      "This model models/gemini-2.5-flash is no longer available to new
       users. Please update your code to use models/gemini-3.6-flash"
    Lấy tên CUỐI CÙNG xuất hiện mà chưa thử — đó là tên được gợi ý,
    không phải tên vừa hỏng.
    """
    for name in reversed(SUGGEST_RE.findall(text or "")):
        if name not in tried:
            return name
    return None


def _complete_gemini(system, user, max_tokens):
    global _GEMINI_MODEL
    if not _env("GEMINI_API_KEY"):
        raise NotAvailable("chưa có GEMINI_API_KEY.\n\n" + setup_hint())

    # Thứ tự ưu tiên: ép thủ công -> đã dùng được trong phiên này ->
    # nhớ từ lần chạy trước -> danh sách tên đã biết.
    # Luôn nối GEMINI_CANDIDATES phía sau: tên đã nhớ vẫn có thể bị Google
    # gỡ bất cứ lúc nào, và khi đó phải còn đường lui.
    queue = []
    for name in (_env("GEMINI_MODEL"), _GEMINI_MODEL, _load_cached_model()):
        if name and name not in queue:
            queue.append(name)
    queue += [c for c in GEMINI_CANDIDATES if c not in queue]

    tried, errors = set(), []

    while queue:
        model = queue.pop(0)
        if not model or model in tried:
            continue
        tried.add(model)

        r = _gemini_call(model, system, user, max_tokens)

        if r.status_code == 200:
            _GEMINI_MODEL = model
            _save_cached_model(model)
            return _gemini_text(r.json())

        body = (r.text or "")[:400]
        errors.append(f"{model}: {r.status_code} {body[:120]}")

        if r.status_code in (401, 403):
            raise NotAvailable(f"GEMINI_API_KEY bị từ chối: {r.status_code} {body}")
        if r.status_code == 429:
            raise RuntimeError(
                "Gemini báo vượt hạn mức (bậc miễn phí ~15 request/phút). "
                "Đợi một phút rồi thử lại."
            )

        # Google gợi ý tên thay thế ngay trong lỗi -> chen lên đầu hàng đợi
        if r.status_code == 404:
            sug = _suggested_model(body, tried)
            if sug:
                queue.insert(0, sug)

    # Hết tên để thử -> hỏi thẳng Google xem hiện có gì
    try:
        found = _gemini_discover()
    except Exception as exc:
        found = None
        errors.append(f"models.list: {exc}")

    if found and found not in tried:
        r = _gemini_call(found, system, user, max_tokens)
        if r.status_code == 200:
            _GEMINI_MODEL = found
            _save_cached_model(found)
            return _gemini_text(r.json())
        errors.append(f"{found}: {r.status_code} {(r.text or '')[:120]}")

    raise RuntimeError(
        "Gemini không trả lời được. Đã thử:\n    "
        + "\n    ".join(errors)
        + '\n\n  Ép một tên cụ thể:  setx GEMINI_MODEL "gemini-3.6-flash"'
    )


def _gemini_text(data):
    cands = data.get("candidates") or []
    if not cands:
        fb = data.get("promptFeedback", {})
        raise RuntimeError(f"Gemini không trả về nội dung: {fb}")

    c = cands[0]
    parts = (c.get("content") or {}).get("parts") or []
    text = "".join(p.get("text", "") for p in parts)
    reason = c.get("finishReason", "")

    if not text.strip():
        if reason == "MAX_TOKENS":
            raise RuntimeError(
                "Gemini hết ngân sách token trước khi viết được câu trả lời "
                "(bước suy luận nội bộ đã tiêu hết). "
                'Nới bằng:  setx GEMINI_MIN_TOKENS 4096'
            )
        raise RuntimeError(f"Gemini trả về rỗng (finishReason={reason or '?'})")

    if reason == "MAX_TOKENS":
        raise RuntimeError(
            "Gemini bị cắt giữa chừng vì hết token — câu trả lời không "
            'trọn vẹn. Nới bằng:  setx GEMINI_MIN_TOKENS 4096'
        )
    return text


# ---------------------------------------------------------------- anthropic
def _complete_anthropic(system, user, max_tokens):
    global _CLIENT
    if not _env("ANTHROPIC_API_KEY"):
        raise NotAvailable("chưa có ANTHROPIC_API_KEY.\n\n" + setup_hint())
    if _CLIENT is None:
        try:
            import anthropic
        except ImportError:
            raise NotAvailable("chưa cài SDK:  pip install anthropic")
        _CLIENT = anthropic.Anthropic(api_key=_env("ANTHROPIC_API_KEY"))

    resp = _CLIENT.messages.create(
        model=ANTHROPIC_MODEL, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(b.text for b in resp.content
                   if getattr(b, "type", "") == "text")


# ------------------------------------------------------------------- ollama
def _complete_ollama(system, user, max_tokens):
    import requests
    model = _env("OLLAMA_MODEL") or OLLAMA_DEFAULT_MODEL
    try:
        r = requests.post(
            f"{OLLAMA_URL}/api/chat",
            json={"model": model, "stream": False,
                  "options": {"temperature": 0, "num_predict": max_tokens},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
            timeout=180,
        )
    except Exception as exc:
        raise NotAvailable(
            f"không kết nối được Ollama ở {OLLAMA_URL}: {exc}\n"
            "  Ollama đã chạy chưa? Thử:  ollama serve"
        )
    if r.status_code == 404:
        raise RuntimeError(
            f"Ollama chưa có model '{model}'. Tải bằng:  ollama pull {model}"
        )
    r.raise_for_status()
    return (r.json().get("message") or {}).get("content", "")


# ------------------------------------------------------------------- public
_BACKENDS = {"gemini": _complete_gemini, "anthropic": _complete_anthropic,
             "ollama": _complete_ollama}


def complete(system, user, max_tokens=DEFAULT_MAX_TOKENS):
    p = provider()
    fn = _BACKENDS.get(p)
    if fn is None:
        raise NotAvailable(setup_hint())
    return fn(system, user, max_tokens)


def complete_json(system, user, max_tokens=DEFAULT_MAX_TOKENS):
    """
    Gọi mô hình và ép ra JSON.

    Mô hình đôi khi bọc JSON trong ```json ... ``` hoặc thêm lời dẫn dù đã
    dặn đừng — mô hình nhỏ chạy qua Ollama đặc biệt hay làm vậy. Bóc vỏ ở
    đây một lần, thay vì để mỗi nơi gọi tự xử lý.
    """
    orig = (complete(system, user, max_tokens) or "").strip()
    raw = orig

    fence = re.search(r"```(?:json)?\s*(.+?)```", raw, re.S)
    if fence:
        raw = fence.group(1).strip()
    else:
        i, j = raw.find("{"), raw.rfind("}")
        if i == -1 or j == -1:
            i, j = raw.find("["), raw.rfind("]")
        if i != -1 and j > i:
            raw = raw[i:j + 1]

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        # In NGUYÊN VĂN thứ mô hình trả về. Bản cũ chỉ in đoạn đã bóc vỏ,
        # nên khi mô hình bị cắt giữa chừng thì thông báo lỗi trông như
        # vô nghĩa và không ai đoán được chuyện gì xảy ra.
        raise ValueError(
            f"mô hình không trả về JSON hợp lệ: {exc}\n"
            f"  Nguyên văn nhận được:\n    {orig[:400]}\n"
            "  Thường là do mô hình bị cắt vì hết token. Thử:\n"
            "    setx GEMINI_MIN_TOKENS 4096"
        )