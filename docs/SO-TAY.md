# Agent thư ký cá nhân — Sổ tay đầy đủ

Trợ lý AI quản lý thời gian, công việc và học tập, chạy trên máy cá nhân,
nối trực tiếp với Google Calendar.

**Trạng thái:** 6 tầng hoàn thành, 21 lệnh, 197 phép thử tự động.

---

# Phần 1 — Dự án đã đi qua những đâu

Phần này quan trọng không kém phần kỹ thuật. Nhiều quyết định trông kỳ quặc
nếu không biết vì sao chúng được đưa ra.

## 1.1. Ý tưởng ban đầu và lý do từ bỏ

Ý tưởng đầu tiên là một **web/app đa nền tảng** quản lý lịch trình, dùng AI
dự đoán thời tiết và giao thông để gợi ý đổi lịch, đổi tuyến đường.

Ba lý do khiến hướng này bị bỏ:

**Nó đã tồn tại.** Google Calendar, Apple Calendar và Waze đều đã có cảnh báo
giờ khởi hành dựa trên giao thông thời gian thực. Ba sản phẩm miễn phí.

**Dữ liệu giao thông Việt Nam không đủ tin cậy**, và API thì đắt. Chi phí mỗi
người dùng mỗi tháng có thể vượt doanh thu ngay từ khi chưa scale.

**Vòng xoáy tử thần của thông báo.** Gợi ý dở → người dùng tắt notification →
sản phẩm mất kênh giá trị duy nhất → rời bỏ.

## 1.2. Ý tưởng thay thế: đo thời gian THẬT

Khoảng trống thật của Google Calendar không phải "thiếu AI" mà là ba điều
mang tính **cấu trúc**, không phải "chưa làm":

- Nó chỉ biết những gì bạn nhập vào. Phần lớn thời gian thật của bạn không
  nằm trong đó.
- Nó không có khái niệm "sức chứa". Nó cho bạn nhét 12 việc vào 8 tiếng mà
  không phản đối một câu.
- Nó không bao giờ hỏi "thực tế hôm qua thế nào". Không có vòng phản hồi.

Từ đó, cú lật quan trọng nhất về mặt kỹ thuật: **thay vì mua dữ liệu giao
thông đắt tiền và không chính xác, hãy đo chính chuyển động thật của người
dùng.** Rủi ro lớn nhất của dự án cũ biến thành lợi thế bền vững nhất của dự
án mới.

## 1.3. Từ sản phẩm thành công cụ cá nhân

Quyết định chuyển từ "sản phẩm cho nhiều người" sang "công cụ cho chính mình"
làm biến mất gần như toàn bộ phần khó: xét duyệt OAuth, Nghị định 13 về dữ
liệu cá nhân, đa nền tảng, App Store, retention, chi phí server.

## 1.4. Những ngã rẽ kỹ thuật và lý do

| Quyết định | Vì sao |
|---|---|
| **Service account** thay vì OAuth | OAuth ở trạng thái Testing khiến token chết sau đúng 7 ngày. Publish lên production thì Google đòi trang chủ + chính sách riêng tư trên domain đã xác minh — vô lý cho app một người dùng |
| **syncToken** thay vì webhook | Webhook đòi domain đã xác minh, HTTPS hợp lệ, và channel hết hạn sau vài ngày nên cần job gia hạn. Bốn bộ phận phải bảo trì. syncToken cho kết quả tương đương với một phần công sức, và **không cần IP công khai** |
| **Bỏ Telegram** | Bị chặn ở Việt Nam. Thay bằng email SMTP và chính Google Calendar làm kênh lệnh |
| **SMTP + App Password** thay vì Gmail API | Gmail API dùng scope *restricted*, khắt khe hơn hẳn Calendar. SMTP là mười dòng code |
| **Gemini** thay vì Anthropic | Bậc miễn phí, không cần thẻ tín dụng |
| **Không dùng LLM ở tầng quyết định** | n quá nhỏ, quan hệ gần như tuyến tính, và bắt buộc phải giải thích được |

## 1.5. Những lỗi đã gặp và cách chữa

| Lỗi | Nguyên nhân | Chữa |
|---|---|---|
| `ZoneInfoNotFoundError` | Windows không có sẵn CSDL múi giờ IANA | `pip install tzdata` |
| `404` khi sync | Dán email service account vào Calendar nhưng **quên bấm Send** | Bấm Send |
| OAuth chết sau 7 ngày | Publishing status = Testing | Chuyển sang service account |
| `AQ.` key lạ | Google đang thay định dạng key `AIza` cũ | Không sao, native endpoint vẫn nhận |
| Gemini `404 model no longer available` | Tên model đổi rất nhanh | Code tự đọc gợi ý trong thông báo lỗi |
| Gemini `400 INVALID_ARGUMENT` | `thinkingConfig` không được Gemini 3.x chấp nhận | Tự bỏ trường đó rồi gọi lại |
| Gemini trả về mảnh vụn | Model 3.x tiêu token cho suy luận nội bộ trước khi viết | Sàn 2048 token |
| `Read timed out` | Đường VN → Google chập chờn | Thử lại 5 lần, giãn cách 1s→8s |

### Hai lỗi nghiêm trọng nhất — cả hai do dữ liệu thật phơi bày

**Bộ đề xuất chỉ xếp một block mỗi ngày cho mỗi việc**, phần còn lại lặng lẽ
biến mất. Nguyên nhân: một ngày trống thường là *một* slot dài 8–14 tiếng, và
code nhảy sang slot hôm sau thay vì dùng nốt chỗ dư. Đề xuất "29/08 2 tiếng,
30/08 2 tiếng" chính là triệu chứng.

**`progress` tự đóng việc khi chạm ước tính.** Nghe hợp lý, nhưng hệ quả là
`done_min` **không bao giờ vượt** `est_min` — nên tỉ lệ thực tế/ước tính bị
chặn cứng ở 1.0. Mà phần vượt quá chính là thứ duy nhất đáng đo. Dụng cụ đo
hỏng, không phải thiếu dữ liệu. Phát hiện khi 4/5 mẫu đầu tiên đều bằng đúng
1.00.

---

# Phần 2 — Kiến trúc sáu tầng

Nguyên tắc xuyên suốt: **tầng dưới không phụ thuộc tầng trên.** Gỡ Tầng 4 ra,
năm tầng còn lại vẫn chạy nguyên vẹn.

```
Tầng 6   Học hệ số lạm phát ước tính
Tầng 5   Hoàn tác, dọn dẹp, kiểm tra sẵn sàng bật quyền ghi
Tầng 4   LLM — hiểu tiếng Việt, hỏi đáp dữ liệu        (tuỳ chọn)
Tầng 3   Báo cáo và gửi email
Tầng 2   Kho công việc, tìm chỗ trống, kiểm tra khả thi
Tầng 1   Xác thực, đồng bộ, lớp ghi có kiểm soát       (nền móng)
```

## Tầng 1 — Nền móng

**Việc:** đọc/ghi Google Calendar, giữ bản sao cục bộ, bốn cầu dao an toàn.

Đây là 60% khối lượng công việc của cả dự án và là phần không ai muốn làm.
Bỏ qua thì mọi thứ sau đều mục.

### Ba cơ chế cốt lõi

**Đồng bộ tăng dần.** Gọi `events.list` kèm `syncToken`, Google chỉ trả về
phần đã thay đổi. Không đổi gì thì trả rỗng, gần như miễn phí. Poll 90 giây
là đủ "thời gian thực" cho một thư ký. Khi token hết hạn Google trả
`410 Gone`; đó không phải lỗi, agent tự làm full sync lại.

**Chống vòng lặp tự kích hoạt.** Agent ghi một sự kiện → sync lần sau thấy đó
là "thay đổi mới" → agent phản ứng với chính hành động của mình → vòng lặp vô
hạn ghi vào lịch thật lúc 3 giờ sáng. Chặn bằng nhãn trong
`extendedProperties.private`:

```json
{"agent": "v1", "rev": "a3f9c2e18b04", "task_id": "7"}
```

Trường `rev` khớp với lần ghi gần nhất thì agent nhận ra tiếng vọng của chính
mình và bỏ qua.

**State nằm ngay trên sự kiện.** Cũng nhờ `extendedProperties`: bạn kéo thả
block trong app Calendar, agent đọc lại vẫn biết block đó thuộc việc nào.
Không cần đồng bộ hai chiều giữa database và lịch.

### Bốn cầu dao

| Cầu dao | Chặn gì |
|---|---|
| `can_write()` | Scope readonly thì mọi thao tác ghi bị từ chối |
| `SHADOW_MODE` | Chỉ ghi nhật ký, không gọi API. **Mặc định BẬT** |
| `QUIET_HOURS` | Không hành động 22h–7h |
| `MAX_WRITES_PER_DAY` | Trần thao tác/ngày, chống vòng lặp hỏng |

Cộng một luật cứng: **agent chỉ được sửa/xoá sự kiện do chính nó tạo.**

Lý do bốn cầu dao đắt hơn giá trị chúng bảo vệ: chế độ hỏng của agent tự chủ
không phải là nó ngu, mà là **nó làm sai lúc bạn đang ngủ**.

## Tầng 2 — Bộ máy quyết định

**Việc:** kho công việc, tìm chỗ trống, kiểm tra khả thi, đề xuất block.

Không có LLM ở đây, và đó là chủ ý. Toàn bộ tất định: cùng đầu vào cho cùng
đầu ra, test được, debug được, giải thích được.

### Kiểm tra khả thi theo EDF tích luỹ

Đây là thứ đáng giá nhất trong cả dự án.

Nó không hỏi "việc này có kịp không" mà **"việc này CỘNG với mọi việc hạn
sớm hơn có kịp không"**. Đây mới là câu đúng, vì bạn không làm hai việc cùng
lúc được.

Ví dụ: hai việc mỗi việc 150 phút, cùng hạn ngày mai, còn 225 phút trống.
Từng việc riêng lẻ đều kịp (150 < 225). Cộng lại thì không (300 > 225).
Kiểm tra từng-việc-một sẽ bỏ sót hoàn toàn.

### Tìm chỗ trống

Lấy khung `WORK_HOURS`, trừ sự kiện đã có, cộng đệm `BUFFER_MIN` hai đầu mỗi
sự kiện, bỏ khoảng ngắn hơn `MIN_BLOCK_MIN`.

**Sự kiện cả ngày bị bỏ qua** khi tính bận. Kỳ nghỉ hay ngày thi đặt dạng
"all day" sẽ *không* chặn được thời gian — cần chặn thì đặt giờ cụ thể.

### Đề xuất block

Tham lam theo EDF, hạn gần nhất trước. Cố tình đơn giản: thuật toán tối ưu
toàn cục không đáng công vì bạn sẽ sửa tay một nửa số đề xuất.

Ba luật nhỏ nhưng quan trọng: không xếp vượt hạn, cộng đệm giữa các block
agent tự xếp, và không để lại phần dư nhỏ hơn một block.

## Tầng 3 — Báo cáo

Nội dung được tách khỏi phần in ra màn hình. Nếu để logic nằm trong hàm
`print` thì bản email sẽ dần lệch khỏi bản terminal — lỗi kinh điển của mọi
hệ thống báo cáo.

Email dùng SMTP với App Password: không bị chặn ở đâu, có trên mọi thiết bị,
tự lưu trữ vĩnh viễn.

## Tầng 4 — LLM (tuỳ chọn)

Nguyên tắc: **LLM đề xuất, code quyết định.**

### Ba nhà cung cấp

Chọn bằng `LLM_PROVIDER`, hoặc tự dò theo thứ tự Gemini → Anthropic → Ollama.
Miễn phí trước.

Mọi lời gọi API tập trung ở đúng một file `llm.py`. Đổi nhà cung cấp chỉ sửa
một file; `nlu.py`, `ask.py` và các rào chắn giữ nguyên từng dòng.

### Ba lớp phòng thủ cho tên model Gemini

1. Thử lần lượt các tên đã biết
2. **Đọc gợi ý Google nhét trong chính thông báo lỗi 404** — lớp bền nhất,
   vì Google luôn nói tên thay thế khi gỡ một model
3. Gọi `models.list` hỏi thẳng

Cộng cache tên đã dùng được sang các lần chạy sau.

### Hai rào chắn cho SQL

1. **Kiểm tra cú pháp** — chỉ cho SELECT/WITH, một câu lệnh, cấm mọi từ khoá ghi
2. **Kết nối chỉ đọc** (`mode=ro`) — SQLite từ chối ở tầng driver

Rào một là danh sách đen, mà danh sách đen thì luôn thiếu thứ gì đó. Rào hai
không dựa vào việc mình đoán đúng.

## Tầng 5 — Bật quyền ghi

Phần lớn Tầng 5 không phải code — `SHADOW_MODE = False` là một dòng. Thứ thật
sự còn thiếu là công cụ bạn cần **khi agent bắt đầu ghi thật**.

Ba luật an toàn:

- Agent chỉ đụng sự kiện **do chính nó tạo**, kể cả khi sự kiện khác vô tình
  mang `task_id`
- `cleanup` chỉ xoá block **trong tương lai**. Block quá khứ là lịch sử
- Gỡ một sự kiện bạn đã tự xoá tay thì agent hiểu, không báo lỗi

## Tầng 6 — Học thói quen ước tính

Câu hỏi: bạn nghĩ 60 phút, thực tế mất bao nhiêu?

Bốn quyết định thống kê, cùng lý do đã dùng ở nơi khác trong dự án:

1. **Mô hình `log(tỉ lệ)`** — vượt gấp đôi (2.0) và xong trong nửa thời gian
   (0.5) phải triệt tiêu nhau. Trên thang log thì đúng, thang thường thì trung
   bình ra 1.25, sai.
2. **Co về 1.0 khi ít dữ liệu** — cùng một công thức chạy từ mẫu thứ nhất tới
   mẫu thứ trăm, không cần chế độ riêng.
3. **Cắt đuôi ở khoảng (0.2, 5.0)** — một việc ước tính 30 phút mà mất 5 tiếng
   không được định đoạt toàn bộ hệ số.
4. **Không dùng mạng nơ-ron** — n cỡ vài chục, quan hệ gần như tuyến tính, và
   bắt buộc phải giải thích được.

### Phát hiện dữ liệu hỏng

Phần được test kỹ nhất **không phải phép tính**, mà là khả năng nhận ra dữ
liệu không đáng tin. Một hệ số tính từ dữ liệu hỏng còn tệ hơn không có hệ số
nào, vì nó trông như thông tin.

Ba cảnh báo tự động: dồn đống ở đúng 1.00 (hiện vật của lỗi tự-đóng-việc),
nhiều việc đóng khi mới làm dưới 40%, và mẫu bị cắt vì ngoài khoảng.

---

# Phần 3 — Toàn bộ 21 lệnh

## Kết nối

| Lệnh | Việc |
|---|---|
| `python run.py check` | Kiểm tra cấu hình, xác thực, sync một lần. **Chạy đầu tiên khi có vấn đề** |
| `python run.py sync` | Đồng bộ một lần rồi thoát |
| `python run.py watch` | Vòng lặp, poll mỗi `POLL_SECONDS` giây. Tự nạp `@task` |
| `python run.py llm` | Xem nhà cung cấp LLM, và **gọi thử một lần thật** |
| `python run.py golive` | Kiểm tra đã sẵn sàng tắt shadow mode chưa |

## Xem

| Lệnh | Việc |
|---|---|
| `python run.py today` | Lịch hôm nay từ bản sao cục bộ, không gọi API |
| `python run.py brief` | **Lệnh chính.** Lịch + việc + khả thi + đề xuất |
| `python run.py review` | Đối chiếu cuối ngày: agent đã đề xuất/làm gì |
| `python run.py log` | 25 hành động gần nhất |
| `python run.py accuracy` | Hệ số lạm phát ước tính của bạn |

`brief` có hai cờ: `--sync` (đồng bộ trước) và `--email` (gửi qua mail).

## Công việc

### `python run.py add "Tên việc" --est 4h --due 30/8`

| Tham số | Nhận |
|---|---|
| `--est` | `240`, `4h`, `90m`, `1h30` |
| `--due` | `30/8`, `30/8/2026`, `2026-08-30`, `mai`, `hôm nay`, `mốt` |
| `--soft` | Hạn mong muốn, không cứng |
| `--force` | Thêm dù đã có việc trùng |

Tự chặn nếu đã có việc y hệt. So tên không phân biệt hoa thường và khoảng
trắng; hạn so **theo ngày** chứ không theo giây.

### `python run.py tasks`
**Số ở cột đầu là số thứ tự hiển thị**, đánh lại liền mạch sau mỗi lần đóng
việc. ID thật giữ nguyên bên trong vì `action_log` và các block trên Calendar
đều tham chiếu tới nó.

### `python run.py progress 1 45`
Ghi nhận đã làm việc số 1 được 45 phút. Số âm để hoàn tác.

**Vượt ước tính thì cứ ghi tiếp** — đó chính là dữ liệu Tầng 6 cần. Việc chỉ
đóng khi bạn gọi `done`.

### `python run.py done 1` / `reopen <id>`
`done` dùng **số thứ tự**. `reopen` dùng **ID thật**, in ra lúc bạn đóng việc.

### `python run.py inbox`
Nạp lệnh `@task` từ Google Calendar:

```
@task Ôn Xác suất | 3h | 10/9
```

Kênh lệnh và kênh dữ liệu là một, nên không bao giờ lệch pha.

### `note` và `ask` *(cần LLM)*
`note "câu tiếng Việt"` — hỏi xác nhận trước khi thêm.
`ask "câu hỏi"` — hỏi trên chính dữ liệu của bạn, `--sql` in cả câu SQL.

## Xếp lịch

| Lệnh | Việc |
|---|---|
| `python run.py plan` | Xếp block. Ghi thật thì cho xem trước rồi hỏi (`-y` bỏ qua) |
| `python run.py undo -n 3` | Gỡ 3 hành động đã ghi thật |
| `python run.py cleanup` | Xoá block của việc đã xong. Chỉ block tương lai |

---

# Phần 4 — Cấu hình

Mở `config.py`.

## Bắt buộc sửa

```python
CALENDAR_ID = "yuhna0811@gmail.com"   # KHÔNG phải "primary"
```

## Hay chỉnh nhất

| Tham số | Mặc định | Ý nghĩa |
|---|---|---|
| `WORK_HOURS` | `(8, 22)` | Khung giờ agent được xếp việc |
| `MAX_BLOCK_MIN` | `120` | Block dài nhất |
| `MIN_BLOCK_MIN` | `30` | Khoảng trống ngắn hơn thì bỏ qua |
| `BUFFER_MIN` | `15` | Đệm hai đầu mỗi sự kiện |
| `HORIZON_DAYS` | `14` | Số ngày nhìn tới khi kiểm tra khả thi |

## An toàn — chỉ đổi khi hiểu rõ

`SHADOW_MODE` (`True`), `SCOPES` (`calendar.readonly`), `QUIET_HOURS`
(`(22, 7)`), `MAX_WRITES_PER_DAY` (`20`).

## Biến môi trường

```
setx GEMINI_API_KEY "AQ..."          key Gemini (miễn phí)
setx GEMINI_MODEL "gemini-3.6-flash" ép một tên model cụ thể
setx LLM_PROVIDER "ollama"           ép nhà cung cấp
setx LLM_RETRIES 8                   số lần thử lại khi mạng chập chờn
setx GEMINI_MIN_TOKENS 4096          nới ngân sách token
```

Sau `setx` phải **mở lại terminal**.

Đặt khoá ở biến môi trường chứ không trong `config.py`, vì `config.py` là file
bạn có thể lỡ tay đưa lên GitHub.

---

# Phần 5 — Các file

## Bố cục thư mục

```
personal-secretary/
├── run.py              điểm vào duy nhất — 21 lệnh
├── config.py           thứ bạn sửa
├── requirements.txt
├── README.md
│
├── (15 module lõi)     auth, store, sync, calendar_ops, tasks, planner,
│                       inbox, report, notify, rollback, golive, estimate,
│                       llm, nlu, ask
│
├── tools/              script chạy tay, KHÔNG phải phần lõi
│   ├── whoami.py         chẩn đoán quyền truy cập lịch
│   ├── demo.py           chạy thử trên lịch giả
│   └── make_schedule.py  sinh .ics từ thời khoá biểu
│
├── docs/
│   ├── SO-TAY.md       file này
│   └── lich-hoc.ics
│
└── tests/              197 phép thử
```

15 module lõi để phẳng ở thư mục gốc là **có chủ ý**: mọi import đều là
`import tasks`, không phải `from secretary.core.tasks import ...`. Với dự án
một người, đơn giản đáng giá hơn đúng chuẩn.

Ba file trong `tools/` tách ra được vì chúng **không được module nào import**
— chúng là script chạy tay. Đó cũng là tiêu chí quyết định cái gì nên tách:
thứ không ai import thì không thuộc về lõi.

## Vai trò từng module

| File | Vai trò |
|---|---|
| `config.py` | Cấu hình — **sửa file này trước** |
| `auth.py` | Xác thực. File **duy nhất** biết đang dùng service account hay OAuth |
| `store.py` | SQLite: bản sao lịch, syncToken, nhật ký hành động |
| `sync.py` | Đồng bộ tăng dần, xử lý 410, chống vòng lặp |
| `calendar_ops.py` | Lớp ghi **duy nhất**, chứa bốn cầu dao |
| `tasks.py` | Kho công việc, đọc ngày/giờ tiếng Việt |
| `planner.py` | Tìm chỗ trống, kiểm tra khả thi, đề xuất |
| `inbox.py` | Đọc lệnh `@task` từ Calendar |
| `report.py` | Dựng nội dung báo cáo |
| `notify.py` | Gửi email SMTP |
| `llm.py` | Lớp bọc LLM, ba nhà cung cấp |
| `nlu.py` | Trích task từ câu tiếng Việt |
| `ask.py` | Hỏi đáp SQL, hai rào chắn |
| `rollback.py` | Hoàn tác và dọn dẹp |
| `golive.py` | Kiểm tra sẵn sàng |
| `estimate.py` | Hệ số lạm phát ước tính |
| `run.py` | CLI, 21 lệnh |

## Kiểm thử — 197 phép thử

| File | Số | Kiểm gì |
|---|---|---|
| `tests/fake_calendar.py` | — | Giả lập Google Calendar API |
| `tests/test_agent.py` | 25 | Sync, chống vòng lặp, bốn cầu dao |
| `tests/test_planner.py` | 52 | Chỗ trống, khả thi EDF, đề xuất, chống trùng |
| `tests/test_llm.py` | 65 | Rào chắn SQL, chọn nhà cung cấp, xử lý lỗi Gemini |
| `tests/test_rollback.py` | 28 | Hoàn tác, dọn dẹp, từ chối đúng lúc |
| `tests/test_estimate.py` | 27 | Hệ số ước tính, phát hiện dữ liệu hỏng |

Bộ giả lập cho phép kiểm chứng mọi thứ **không cần mạng, không cần tài khoản
Google, và không rủi ro nghịch vào lịch thật.**

## Không đưa lên GitHub

```
service_account.json
credentials.json
token.json
*.db
.llm_model_cache
```

---

# Phần 6 — Xử lý sự cố

| Triệu chứng | Nguyên nhân |
|---|---|
| `404 Not Found` | `CALENDAR_ID` sai, hoặc chưa share lịch (thường là **quên bấm Send**) |
| `403 Forbidden` | Chưa Enable Calendar API, hoặc quyền share thấp hơn scope |
| `invalid_grant` | Cái bẫy 7 ngày (OAuth ở Testing) |
| `ZoneInfoNotFoundError` | `pip install tzdata` |
| `ModuleNotFoundError` | Chạy `python -m tests.test_planner` |
| `Sẵn sàng: KHÔNG` (llm) | Chưa mở lại terminal sau `setx` |
| Gemini `404 model` | Code tự dò. Vẫn hỏng thì `setx GEMINI_MODEL "..."` |
| Gemini `429` | Chạm 15 request/phút bậc miễn phí. Đợi một phút |
| `Read timed out` | Mạng chập chờn. `setx LLM_RETRIES 8` |
| Mô hình trả mảnh vụn | `setx GEMINI_MIN_TOKENS 4096` |

Gặp lỗi truy cập lịch thì chạy `python tools/whoami.py` — nó hỏi thẳng Google
xem service account đang thấy được những lịch nào.

---

# Phần 7 — Công việc hàng ngày

## Mỗi tối, ~1 phút

```
python run.py progress <số> <phút>
```

Vượt ước tính thì cứ ghi tiếp. Xong hẳn mới `done`.

## Vài lần trong tuần

```
python run.py plan
python run.py log
```

`golive` đòi 15 đề xuất, mà đề xuất chỉ sinh ra khi bạn chạy `plan`.

## Vài ngày một lần

```
python run.py brief
python run.py accuracy
```

## Việc quan trọng nhất lại không phải lệnh

Mỗi lần đọc phần ĐỀ XUẤT, tự hỏi: *nếu agent ghi những block này lên lịch
tôi, tôi có làm theo không?* Ghi lại chỗ nào sai.

| Vấn đề | Chỗ sửa |
|---|---|
| Xếp lúc 8h mà bạn không dậy nổi | `WORK_HOURS` |
| Khối 2 tiếng quá dài | `MAX_BLOCK_MIN` |
| Xếp vào giờ ăn, giờ đi lại | Thêm sự kiện lặp lại trên Calendar |
| Quá dày, không có chỗ thở | `BUFFER_MIN` |

## Đẩy code lên GitHub

```
git add -A
git status --short
git commit -m "mô tả ngắn"
git push
```

Bước 2 đừng bỏ. Mỗi lần chép đè file mới là một cơ hội cho file lạ lọt vào.

---

# Phụ lục — Bốn nguyên tắc thiết kế

**1. LLM đề xuất, code quyết định.**
LLM ngồi ở tầng dịch ngôn ngữ, không ngồi ở tầng quyết định. Nó chậm, đắt,
không tái lập được và không debug được. Mọi đầu ra của nó bị code kiểm tra
lại từ đầu.

**2. Chế độ hỏng không phải là agent ngu, mà là nó sai lúc bạn đang ngủ.**
Đó là lý do có bốn cầu dao, shadow mode mặc định bật, giờ yên tĩnh, và luật
chỉ-đụng-sự-kiện-của-chính-mình.

**3. Cô lập thứ hay đổi vào một file.**
`auth.py` là file duy nhất biết backend xác thực. `llm.py` là file duy nhất
gọi API mô hình. `calendar_ops.py` là nơi duy nhất được ghi. Nhờ vậy đổi từ
OAuth sang service account, hay từ Anthropic sang Gemini, chỉ tốn một lần sửa.

**4. Test cái sẽ hỏng, không test cái dễ test.**
197 phép thử phần lớn kiểm tra hệ thống có **từ chối đúng lúc** không: rào
chắn SQL có chặn `DELETE` không, agent có từ chối xoá sự kiện của bạn không,
`accuracy` có nhận ra dữ liệu hỏng không. Bộ giả lập Calendar cho phép kiểm
chứng mọi thứ mà không rủi ro nghịch vào lịch thật.