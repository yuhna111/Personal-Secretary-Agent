"""
Xác thực. Đây là file DUY NHẤT trong dự án biết agent đang dùng service
account hay OAuth. Mọi module khác chỉ gọi get_calendar_service() và không
quan tâm đằng sau là gì — nên đổi backend chỉ tốn một lần sửa file này.

Hai backend:

  service_account  Không hết hạn, không consent screen, không publish app,
                   không cảnh báo "unverified app". Bù lại: không mời được
                   người khác vào sự kiện (thiếu Domain-Wide Delegation).
                   Bạn phải share lịch cho email của service account.

  oauth            Mời được người khác. Bù lại: nếu app còn ở trạng thái
                   Testing thì refresh token CHẾT SAU 7 NGÀY. Muốn sống lâu
                   phải publish app lên In production, và Google sẽ đòi
                   home page + privacy policy.
"""

import os
import sys

import config as cfg

_SERVICE = None


def _resolve_backend():
    if cfg.AUTH_BACKEND != "auto":
        return cfg.AUTH_BACKEND
    if os.path.exists(_p(cfg.SERVICE_ACCOUNT_FILE)):
        return "service_account"
    if os.path.exists(_p(cfg.OAUTH_CLIENT_FILE)):
        return "oauth"
    return None


def _p(name):
    return name if os.path.isabs(name) else os.path.join(cfg.BASE_DIR, name)


# ------------------------------------------------------------ service account
def _creds_service_account():
    from google.oauth2 import service_account

    path = _p(cfg.SERVICE_ACCOUNT_FILE)
    creds = service_account.Credentials.from_service_account_file(
        path, scopes=cfg.SCOPES
    )
    return creds


# ------------------------------------------------------------------- oauth
def _creds_oauth():
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow

    token_path = _p(cfg.OAUTH_TOKEN_FILE)
    creds = None

    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, cfg.SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(token_path, creds)
            return creds
        except Exception as exc:
            # invalid_grant ở đây gần như luôn là cái bẫy 7 ngày của
            # publishing status = Testing. Nói thẳng ra thay vì để người
            # dùng đi tìm nguyên nhân trong vô vọng.
            print(f"\n[auth] Không làm mới được token: {exc}")
            print("[auth] Nguyên nhân phổ biến nhất: app đang ở trạng thái")
            print("       Testing, nên uỷ quyền hết hạn sau đúng 7 ngày.")
            print("       Xử lý: publish app lên In production, hoặc chuyển")
            print("       sang service account (xem README).\n")
            creds = None

    flow = InstalledAppFlow.from_client_secrets_file(
        _p(cfg.OAUTH_CLIENT_FILE), cfg.SCOPES
    )
    creds = flow.run_local_server(port=0)
    _save_token(token_path, creds)
    return creds


def _save_token(path, creds):
    with open(path, "w", encoding="utf-8") as f:
        f.write(creds.to_json())


# -------------------------------------------------------------------- public
def get_calendar_service(force_new=False):
    """Trả về resource `service` của Google Calendar API v3."""
    global _SERVICE
    if _SERVICE is not None and not force_new:
        return _SERVICE

    from googleapiclient.discovery import build

    backend = _resolve_backend()
    if backend is None:
        sys.exit(
            "Không tìm thấy file xác thực nào.\n"
            f"  Cần {cfg.SERVICE_ACCOUNT_FILE} (khuyên dùng) "
            f"hoặc {cfg.OAUTH_CLIENT_FILE}\n"
            "  Xem README phần Cài đặt."
        )

    creds = _creds_service_account() if backend == "service_account" else _creds_oauth()

    _SERVICE = build("calendar", "v3", credentials=creds, cache_discovery=False)
    print(f"[auth] backend = {backend}")
    return _SERVICE


def can_write():
    """Scope hiện tại có cho phép ghi không."""
    return any(s.endswith("/calendar") or s.endswith("/calendar.events")
               for s in cfg.SCOPES)
