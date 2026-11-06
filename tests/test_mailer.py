"""OTP email delivery: dev log fallback and SMTP transport."""

from __future__ import annotations

import smtplib


def test_dev_mailer_records_code_and_echo(container, invite):
    payload = container.auth.request_otp("mailer@example.com", invite=invite)
    assert payload["delivered"] is False  # no SMTP in dev
    assert container.mailer.sent[-1]["to"] == "mailer@example.com"
    assert container.mailer.sent[-1]["code"] == payload["dev_code"]


def test_smtp_mailer_sends_message(monkeypatch):
    from saas.mailer import SmtpMailer

    captured = {}

    class FakeSMTP:
        def __init__(self, host, port, timeout=10):
            captured["host"] = host
            captured["port"] = port

        def ehlo(self):
            return None

        def starttls(self, context=None):
            captured["starttls"] = True

        def login(self, user, password):
            captured["login"] = (user, password)

        def send_message(self, message):
            captured["message"] = message

        def quit(self):
            return None

    monkeypatch.setattr(smtplib, "SMTP", FakeSMTP)
    mailer = SmtpMailer(
        host="smtp.example.com",
        port=2525,
        username="bot",
        password="secret",
        from_addr="bot@example.com",
        from_name="AstrBot",
    )
    assert mailer.send_otp("user@example.com", "654321", expires_minutes=10) is True
    assert captured["host"] == "smtp.example.com"
    assert captured["port"] == 2525
    assert captured["starttls"] is True
    assert captured["login"] == ("bot", "secret")
    body = captured["message"].get_content()
    assert "654321" in body
    assert captured["message"]["To"] == "user@example.com"


def test_auth_uses_injected_mailer(container, invite):
    from saas.mailer import LogMailer

    sent = []

    class RecordingMailer:
        def send_otp(self, to, code, *, expires_minutes):
            sent.append((to, code, expires_minutes))
            return True

    container.auth.mailer = RecordingMailer()
    payload = container.auth.request_otp("injected@example.com", invite=invite)
    assert sent and sent[-1][0] == "injected@example.com"
    assert sent[-1][1] == payload["dev_code"]
    assert payload["delivered"] is True
    assert isinstance(LogMailer(), LogMailer)
