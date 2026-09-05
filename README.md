# Agent thư ký cá nhân

Trợ lý quản lý thời gian, công việc và học tập. Chạy trên máy cá nhân, nối
trực tiếp với Google Calendar.

**6 tầng · 21 lệnh · 197 phép thử tự động**

Thứ nó nói được mà Google Calendar không bao giờ nói:

```
KHÔNG KỊP:
  2. Ôn Xác suất thống kê
     cần 8h00 trước 05/09, chỉ có 5h30 -> thiếu 2h30

  ('cần' là con số tích luỹ, gồm cả việc hạn sớm hơn,
   vì bạn không làm hai việc cùng lúc được)
```

Tài liệu đầy đủ: [`docs/SO-TAY.md`](docs/SO-TAY.md)

---

## Xem thử trước khi cài gì

```
pip install -r requirements.txt
python tools/demo.py
```

Chạy toàn bộ agent trên bộ giả lập. Không cần credentials, không cần mạng,
không đụng lịch thật.

Kiểm chứng logic:

```
python tests/test_agent.py
python tests/test_planner.py
python tests/test_llm.py
python tests/test_rollback.py
python tests/test_estimate.py
```

Tổng 197 phép thử.

---

## Cài đặt — Service account (khuyên dùng)

Không consent screen, không publish app, không privacy policy, **không có
hạn 7 ngày**.

**1.** [console.cloud.google.com](https://console.cloud.google.com) → tạo
project → APIs & Services → Library → **Google Calendar API** → Enable

**2.** IAM & Admin → **Service Accounts** → Create service account → tên
`agent-lich` → bỏ trống phần role → Done

**3.** Bấm vào service account → tab **Keys** → Add key → Create new key →
**JSON**. Lưu vào thư mục dự án, đổi tên `service_account.json`

**4.** Chép email service account (dạng
`agent-lich@<project>.iam.gserviceaccount.com`)

**5.** [calendar.google.com](https://calendar.google.com) → di chuột vào lịch
chính → ⋮ → **Settings and sharing** → **Share with specific people or
groups** → Add people → dán email → quyền **See all event details** →
**Send**

**6.** Sửa `config.py`: `CALENDAR_ID` = địa chỉ Gmail của bạn

```
python run.py check
```

> Hai chỗ hay sai: `CALENDAR_ID` phải là email của bạn, **không phải**
> `"primary"` (với service account, `primary` trỏ vào lịch trống của chính
> nó). Và ở bước 5, dán email vào ô rồi **phải bấm Send** — quên bấm là
> không có gì được lưu.

Gặp lỗi 404 hoặc 403: `python tools/whoami.py` sẽ hỏi thẳng Google xem
service account đang thấy được những lịch nào.

### Hạn chế

Service account **không mời được người khác vào sự kiện** (cần Domain-Wide
Delegation, chỉ có ở Workspace). Với thư ký chỉ xếp block lên lịch của chính
bạn thì không ảnh hưởng.

---

## Cài đặt — LLM (tuỳ chọn)

Chỉ cần cho hai lệnh `note` và `ask`. Không cài thì **19 lệnh còn lại vẫn
chạy bình thường** — LLM là lớp tiện nghi, không phải lớp nền.

**Gemini — miễn phí, không cần thẻ tín dụng:**

```
setx GEMINI_API_KEY "AQ..."
```

Lấy key tại [aistudio.google.com/apikey](https://aistudio.google.com/apikey).
Sau `setx` phải **mở lại terminal**.

**Ollama — miễn phí, chạy trên máy bạn:**

```
ollama pull qwen2.5:7b
setx LLM_PROVIDER ollama
```

Kiểm tra:

```
python run.py llm
```

---

## 21 lệnh

### Kết nối
| Lệnh | Việc |
|---|---|
| `check` | Kiểm tra xác thực + sync. **Chạy đầu tiên khi có vấn đề** |
| `sync` | Đồng bộ một lần |
| `watch` | Vòng lặp, poll mỗi 90 giây |
| `llm` | Kiểm tra cấu hình LLM, gọi thử một lần thật |
| `golive` | Kiểm tra đã sẵn sàng bật quyền ghi chưa |

### Xem
| Lệnh | Việc |
|---|---|
| `brief` | **Lệnh chính.** Lịch + việc + khả thi + đề xuất |
| `today` | Lịch hôm nay |
| `review` | Đối chiếu cuối ngày |
| `log` | Nhật ký hành động |
| `accuracy` | Hệ số lạm phát ước tính của bạn |

`brief` có `--sync` và `--email`.

### Công việc
```
python run.py add "Viết báo cáo" --est 4h --due 30/9
python run.py tasks
python run.py progress 1 45
python run.py done 1
python run.py reopen <id>
python run.py inbox
python run.py note "tuần sau nộp bài tập, chắc 3 tiếng"     (cần LLM)
python run.py ask "tôi còn bao nhiêu việc?"                 (cần LLM)
```

`--est` nhận `240`, `4h`, `90m`, `1h30`. `--due` nhận `30/9`, `30/9/2026`,
`mai`, `hôm nay`, `mốt`.

Nhập từ điện thoại: tạo sự kiện trên Google Calendar tên
`@task Ôn Xác suất | 3h | 10/9`, rồi `python run.py inbox`.

### Xếp lịch
```
python run.py plan
python run.py undo -n 3
python run.py cleanup
```

---

## Vòng lặp hàng ngày

**Mỗi tối, ~1 phút:**
```
python run.py progress <số> <phút>
```

Vượt ước tính thì **cứ ghi tiếp**. Xong hẳn mới `done`. Đây là dữ liệu duy
nhất mà không nguồn nào khác có.

**Vài lần trong tuần:** `plan` rồi `log` — đọc đề xuất và đánh giá.

**Vài ngày một lần:** `brief` và `accuracy`.

---

## Shadow mode

`SHADOW_MODE = True` là mặc định. Agent làm mọi thứ trừ bước cuối: đọc lịch,
phát hiện xung đột, tính đề xuất, ghi vào `action_log` những gì nó *định*
làm. Bạn chạy `python run.py log` mỗi tối và đọc.

Giữ nguyên **ít nhất 3–4 tuần**. Đây không phải sự thận trọng thừa — đó là
cách duy nhất để bạn tin agent đủ mức cho nó quyền ghi vào lịch thật.

Khi thấy sẵn sàng:

```
python run.py golive
```

Nó kiểm tra bốn điều kiện kỹ thuật và nhắc hai câu chỉ bạn trả lời được.

---

## Bốn cầu dao an toàn

| Cầu dao | Chặn gì |
|---|---|
| `can_write()` | Scope readonly thì mọi thao tác ghi bị từ chối |
| `SHADOW_MODE` | Chỉ ghi log, không gọi API |
| `QUIET_HOURS` | Không hành động 22h–7h |
| `MAX_WRITES_PER_DAY` | Trần thao tác/ngày, chống vòng lặp hỏng |

Cộng một luật cứng: **agent chỉ được sửa/xoá sự kiện do chính nó tạo.**

Chế độ hỏng của agent tự chủ không phải là nó ngu, mà là **nó làm sai lúc bạn
đang ngủ**. Một lần tự huỷ buổi họp quan trọng là bạn tắt nó vĩnh viễn.

---

## Cấu trúc

```
personal-secretary/
├── run.py              điểm vào duy nhất
├── config.py           thứ bạn sửa
├── requirements.txt
│
├── (15 module lõi)     auth, store, sync, calendar_ops, tasks, planner,
│                       inbox, report, notify, rollback, golive, estimate,
│                       llm, nlu, ask
│
├── tools/              script chạy tay, không phải phần lõi
│   ├── whoami.py         chẩn đoán quyền truy cập lịch
│   ├── demo.py           chạy thử trên lịch giả
│   └── make_schedule.py  sinh .ics từ thời khoá biểu
│
├── docs/SO-TAY.md      tài liệu đầy đủ
└── tests/              197 phép thử
```

**Đừng đưa lên GitHub:** `service_account.json`, `credentials.json`,
`token.json`, `*.db`, `.llm_model_cache`. Đã có sẵn trong `.gitignore`.

---

## Bốn nguyên tắc thiết kế

**1. LLM đề xuất, code quyết định.** LLM ngồi ở tầng dịch ngôn ngữ, không
ngồi ở tầng quyết định. Mọi đầu ra của nó bị code kiểm tra lại từ đầu.

**2. Chế độ hỏng không phải agent ngu, mà là nó sai lúc bạn đang ngủ.** Đó là
lý do có bốn cầu dao và luật chỉ-đụng-sự-kiện-của-chính-mình.

**3. Cô lập thứ hay đổi vào một file.** `auth.py` là file duy nhất biết
backend xác thực. `llm.py` là file duy nhất gọi API mô hình.
`calendar_ops.py` là nơi duy nhất được ghi.

**4. Test cái sẽ hỏng, không test cái dễ test.** Phần lớn 197 phép thử kiểm
tra hệ thống có **từ chối đúng lúc** không: rào chắn SQL có chặn `DELETE`
không, agent có từ chối xoá sự kiện của bạn không, `accuracy` có nhận ra dữ
liệu hỏng không.

---

## Lỗi hay gặp

| Triệu chứng | Nguyên nhân |
|---|---|
| `404 Not Found` | `CALENDAR_ID` sai, hoặc quên bấm **Send** khi share lịch |
| `403 Forbidden` | Chưa Enable Calendar API |
| `ZoneInfoNotFoundError` | `pip install tzdata` (Windows không có sẵn CSDL múi giờ) |
| `Sẵn sàng: KHÔNG` (llm) | Chưa mở lại terminal sau `setx` |
| Gemini `429` | Chạm 15 request/phút bậc miễn phí. Đợi một phút |
| `Read timed out` | Mạng chập chờn. `setx LLM_RETRIES 8` |

Bảng đầy đủ trong [`docs/SO-TAY.md`](docs/SO-TAY.md).