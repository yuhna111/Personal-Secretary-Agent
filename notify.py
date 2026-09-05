"""
Gửi email qua SMTP.

Vì sao SMTP mà không phải Gmail API: Gmail API dùng scope RESTRICTED, khắt
khe hơn hẳn Calendar, và với app cá nhân chưa xác minh thì rủi ro bị Google
siết lại bất cứ lúc nào. SMTP với App Password là cửa sau chính thức, ổn
định nhiều năm nay, và cả module này gói gọn trong mười dòng thật sự.

Điều kiện: tài khoản Google phải BẬT XÁC THỰC 2 BƯỚC, sau đó tạo App
Password riêng cho ứng dụng này. Không dùng mật khẩu Gmail thường được.
"""

import smtplib
import ssl
from email.message import EmailMessage

import config as cfg


class NotConfigured(Exception):
    pass


def _check():
    if not getattr(cfg, "SMTP_USER", "") or "@" not in cfg.SMTP_USER:
        raise NotConfigured("chưa điền SMTP_USER trong config.py")
    if not getattr(cfg, "SMTP_APP_PASSWORD", "") or \
            cfg.SMTP_APP_PASSWORD.startswith("DIEN_"):
        raise NotConfigured(
            "chưa điền SMTP_APP_PASSWORD. Tạo tại "
            "myaccount.google.com/apppasswords (phải bật 2FA trước)"
        )


def send(subject, body, to=None, sender=None):
    """Gửi email dạng text thuần + bản HTML dùng <pre> để giữ căn cột."""
    _check()
    to = to or getattr(cfg, "NOTIFY_TO", None) or cfg.SMTP_USER
    sender = sender or cfg.SMTP_USER

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to
    msg.set_content(body)

    # Bản HTML: <pre> giữ nguyên căn cột trên điện thoại. Không có nó,
    # mọi bảng biểu trong báo cáo sẽ vỡ hết trên Gmail app.
    esc = (body.replace("&", "&amp;").replace(
        "<", "&lt;").replace(">", "&gt;"))
    msg.add_alternative(
        f'<pre style="font-family:ui-monospace,Menlo,Consolas,monospace;'
        f'font-size:13px;line-height:1.45;white-space:pre-wrap">{esc}</pre>',
        subtype="html",
    )

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx, timeout=30) as s:
        s.login(cfg.SMTP_USER, cfg.SMTP_APP_PASSWORD)
        s.send_message(msg)

    return to
