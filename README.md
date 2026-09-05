# Agent thư ký cá nhân — Tầng 1

Đọc/ghi Google Calendar theo thời gian thực, có bốn cầu dao an toàn.

Chưa có LLM. Chưa có logic lập kế hoạch. Đây là nền móng — 60% khối lượng công việc của cả dự án, và là phần không ai muốn làm nhưng bỏ qua thì mọi thứ sau đều mục.

---

## Xem thử trước khi cài gì

```
pip install google-api-python-client google-auth google-auth-oauthlib
python demo.py
```

Chạy toàn bộ agent trên bộ giả lập. Không cần credentials, không cần mạng, không đụng lịch thật.

Kiểm chứng logic:

```
python tests/test_agent.py
```

25 phép thử, gồm sync tăng dần, chống vòng lặp tự kích hoạt, và cả bốn cầu dao.

---

## Cài đặt — Service account (khuyên dùng)

Không consent screen, không publish app, không privacy policy, **không có hạn 7 ngày**.

**1.** [console.cloud.google.com](https://console.cloud.google.com) → tạo project → APIs & Services → Library → **Google Calendar API** → Enable

**2.** IAM & Admin → **Service Accounts** → Create service account → tên `agent-lich` → bỏ trống phần role → Done

**3.** Bấm vào service account → tab **Keys** → Add key → Create new key → **JSON**

Lưu file vào thư mục dự án, đổi tên thành `service_account.json`.

**4.** Chép email của service account (dạng `agent-lich@<project>.iam.gserviceaccount.com`)

**5.** [calendar.google.com](https://calendar.google.com) → di chuột vào lịch chính → ⋮ → **Settings and sharing** → **Share with specific people or groups** → Add people → dán email vào → quyền **See all event details**

**6.** Sửa `config.py`: `CALENDAR_ID` = địa chỉ Gmail của bạn

```
python run.py check
```

> `CALENDAR_ID` phải là email của bạn, **không phải** `"primary"`. Với service account, `primary` trỏ vào lịch trống của chính nó.

### Hạn chế

Service account **không mời được người khác vào sự kiện** (cần Domain-Wide Delegation, chỉ có ở Workspace). Với thư ký chỉ xếp block lên lịch của chính bạn thì không ảnh hưởng. Khi nào cần mời họp, lúc đó mới chuyển sang OAuth.

Sự kiện agent tạo hiển thị service account là người tổ chức. Nhìn hơi lạ nhưng lại tiện — phân biệt ngay sự kiện nào do agent tạo.

---

## Cài đặt — OAuth (nếu cần mời người khác)

**1–2.** Giống trên (tạo project, Enable API)

**3.** `console.cloud.google.com/auth/overview` → Get started → App name, email → **External** → Create

**4.** Tab **Data Access** → Add scopes → `calendar.readonly`

**5.** Tab **Audience** → **PUBLISH APP**

**6.** Tab **Clients** → Create client → **Desktop app** → Download JSON → đổi tên `credentials.json`

**7.** `config.py`: `CALENDAR_ID = "primary"`

### Cái bẫy 7 ngày

Nếu bạn **bỏ qua bước 5** và để app ở trạng thái Testing, uỷ quyền hết hạn sau đúng 7 ngày. Agent chạy ngon một tuần rồi trả `invalid_grant` và bạn phải đăng nhập lại. Mỗi tuần. Vĩnh viễn.

Hầu hết tutorial trên mạng bỏ qua chi tiết này vì tác giả chỉ test trong một buổi.

Khi bấm PUBLISH APP, Google có thể báo *"OAuth configuration is incomplete… visit the Branding page"* — nghĩa là nó đòi **App home page** và **Privacy policy** trên một domain bạn sở hữu. Cách rẻ nhất là dựng hai trang tĩnh trên GitHub Pages rồi xác minh domain qua Google Search Console. Nếu thấy vô lý cho một app chỉ mình bạn dùng — đó chính là lý do tôi khuyên service account.

---

## Sử dụng

| Lệnh | Việc |
|---|---|
| `python run.py check` | Kiểm tra xác thực + sync một lần. **Chạy cái này trước** |
| `python run.py sync` | Đồng bộ một lần rồi thoát |
| `python run.py watch` | Vòng lặp, poll mỗi 90 giây |
| `python run.py today` | In lịch hôm nay từ bản sao cục bộ |
| `python run.py log` | Agent đã làm / định làm những gì |

---

## Bốn quyết định thiết kế

### 1. syncToken thay cho webhook

Google Calendar có push notification thật, nhưng nó đòi domain đã xác minh, HTTPS hợp lệ, và channel hết hạn sau vài ngày nên phải có job gia hạn — bốn bộ phận phải bảo trì, đổi lấy một tín hiệu "có gì đó đã đổi" mà bạn vẫn phải gọi API để biết đổi cái gì.

`syncToken` cho kết quả tương đương với một phần công sức. Không đổi gì thì trả về rỗng, gần như miễn phí.

**Hệ quả tốt:** không cần webhook nghĩa là không cần IP công khai. Chạy được trên máy ở nhà, Raspberry Pi, hay cron của GitHub Actions. VPS thành tuỳ chọn.

Khi token hết hạn Google trả `410 Gone` — không phải lỗi, agent tự làm full sync lại.

### 2. extendedProperties làm nơi chứa state

Mỗi sự kiện cho phép đính kèm dữ liệu key-value riêng tư mà giao diện Calendar không hiển thị:

```json
"extendedProperties": {"private": {
  "agent": "v1", "rev": "a3f9c2e18b04", "task_id": "7"
}}
```

Hai công dụng:

- **Chống vòng lặp tự kích hoạt.** Agent ghi một sự kiện → sync lần sau thấy đó là "thay đổi mới" → agent phản ứng với chính hành động của mình → vòng lặp vô hạn ghi vào lịch thật lúc 3 giờ sáng. Trường `rev` chặn việc này.
- **State nằm ngay trên sự kiện.** Bạn kéo thả block trong app Calendar, agent đọc lại vẫn biết block đó thuộc task nào. Không cần đồng bộ hai chiều giữa DB và lịch.

### 3. Bốn cầu dao

| Cầu dao | Chặn cái gì |
|---|---|
| `can_write()` | Scope readonly thì mọi thao tác ghi bị từ chối |
| `SHADOW_MODE` | Chỉ ghi log, không gọi API. **Mặc định BẬT** |
| `QUIET_HOURS` | Không hành động 22h–7h |
| `MAX_WRITES_PER_DAY` | Trần thao tác/ngày, chống vòng lặp hỏng |

Cộng thêm một luật cứng trong code: **agent chỉ được sửa/xoá sự kiện do chính nó tạo.** Đụng vào sự kiện của bạn hoặc của người khác là thao tác không hoàn tác được, phải hỏi trước.

Chế độ hỏng của agent tự chủ không phải là nó ngu, mà là nó làm sai lúc bạn đang ngủ. Một lần tự huỷ buổi họp quan trọng là bạn tắt nó vĩnh viễn.

### 4. Xác thực bị cô lập trong một file

`auth.py` là file duy nhất biết đang dùng service account hay OAuth. Mọi module khác chỉ gọi `get_calendar_service()`. Đổi backend = sửa một file, không đụng gì khác.

---

## Shadow mode

`SHADOW_MODE = True` là mặc định, và nên giữ nguyên **ít nhất 3–4 tuần**.

Agent làm mọi thứ trừ bước cuối: đọc lịch, phát hiện xung đột, tính toán đề xuất, ghi vào `action_log` những gì nó *định* làm. Bạn chạy `python run.py log` mỗi tối và đọc.

Chỉ tắt shadow mode khi bạn đã đọc log 3 tuần liền mà không thấy đề xuất nào ngu ngốc. Đây không phải sự thận trọng thừa — đó là cách duy nhất để bạn tin agent đủ mức cho nó quyền ghi vào lịch thật.

Khi tắt, làm theo thứ tự này:

1. `SCOPES` → `.../auth/calendar.events`
2. Nâng quyền chia sẻ lịch lên **Make changes to events**
3. Xoá `token.json` nếu dùng OAuth (đổi scope phải đồng ý lại)
4. `SHADOW_MODE = False`

---

## Cấu trúc

| File | Vai trò |
|---|---|
| `config.py` | Cấu hình — **sửa trước tiên** |
| `auth.py` | Xác thực, cô lập hai backend |
| `store.py` | SQLite: bản sao lịch, syncToken, nhật ký hành động |
| `sync.py` | Đồng bộ tăng dần, xử lý 410, chống vòng lặp |
| `calendar_ops.py` | Lớp ghi duy nhất, chứa bốn cầu dao |
| `run.py` | CLI |
| `demo.py` | Chạy thử trên giả lập |
| `tests/` | Bộ giả lập Calendar API + 25 phép thử |

**Đừng đưa `service_account.json`, `credentials.json`, `token.json` lên GitHub.**

---

## Lỗi hay gặp

| Triệu chứng | Nguyên nhân |
|---|---|
| `404 Not Found` | `CALENDAR_ID` sai, hoặc chưa share lịch cho service account |
| `403 Forbidden` | Chưa Enable Calendar API, hoặc quyền share thấp hơn scope đang xin |
| `invalid_grant` | Cái bẫy 7 ngày (OAuth ở trạng thái Testing) |
| `This app is blocked` | Tài khoản trường/công ty chặn app chưa xác minh. Dùng Gmail cá nhân |
| Share lịch bị chặn | Quản trị viên chặn chia sẻ ra ngoài tổ chức. Phải dùng OAuth |

---

## Tầng 5 — Bật quyền ghi

Ba lệnh mới, và bạn nên có cả ba TRƯỚC khi tắt shadow mode:

| Lệnh | Việc |
|---|---|
| `python run.py golive` | Kiểm tra đã sẵn sàng bật chưa |
| `python run.py undo -n 3` | Gỡ 3 hành động agent vừa ghi |
| `python run.py cleanup` | Xoá block của việc đã xong hoặc đã bỏ |

### golive kiểm tra gì

Bốn điều kiện đúng/sai rõ ràng: đủ 15 đề xuất, đủ 7 ngày shadow, scope cho
phép ghi, lịch đã chia sẻ quyền `writer`.

Và nhắc hai câu chỉ bạn trả lời được — quan trọng hơn bốn cái trên:

1. Bạn đã **đọc** các đề xuất chưa, hay chỉ để chúng tích lại?
2. Bao nhiêu phần trăm bạn thấy hợp lý? Trên 80% thì bật được.

### Thứ tự bật

1. `config.py`: `SCOPES = [".../auth/calendar.events"]`
2. Google Calendar → Settings and sharing → quyền service account thành
   **Make changes to events**
3. `python run.py check`
4. `config.py`: `SHADOW_MODE = False`
5. `python run.py plan --limit 2` — **hai** block, không phải sáu
6. Mở Calendar xem
7. Không ưng: `python run.py undo -n 2`

Bước 5 cố ý nhỏ. Lần ghi thật đầu tiên nên là thứ bạn gỡ được trong mười
giây, không phải sáu sự kiện rải khắp tuần.

### Ba luật an toàn không đổi

- Agent chỉ sửa/xoá sự kiện **do chính nó tạo** — nhận qua nhãn trong
  `extendedProperties.private`. Sự kiện của bạn không bao giờ bị đụng, kể
  cả khi nó vô tình mang `task_id`.
- `cleanup` chỉ xoá block **trong tương lai**. Block quá khứ là lịch sử.
- Gỡ một sự kiện bạn đã tự xoá tay thì agent hiểu và bỏ qua, không báo lỗi
  và không thử lại mãi.

## Tiếp theo

**Tầng 2 — bộ máy quyết định thuần code.** Phát hiện xung đột, tìm chỗ trống, kiểm tra khả thi. Vẫn chưa có LLM, và bạn sẽ ngạc nhiên vì phần lớn giá trị của "thư ký" nằm ở đây. Móc vào chỗ đã đánh dấu trong `run.py::cmd_watch`.

**Tầng 6 — học thói quen.** So `est_min` với tổng `done_min` thực tế để
tính hệ số lạm phát ước tính của bạn: nghĩ 60 phút, thực tế bao nhiêu.
Cần khoảng 25 lần `progress` mới có gì để tính.

**Tầng 4 — LLM.** Chỉ để hiểu ngôn ngữ tự nhiên và diễn đạt kết quả. Planner đề xuất JSON có cấu trúc; executor là code thuần, validate lại từ đầu rồi mới gọi API. **Không bao giờ để LLM cầm trực tiếp quyền xoá.**