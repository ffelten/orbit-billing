"""Outbound email transport.

Per ADR-0004, nothing in this module is wired to charges or webhooks — it is
the send mechanism only. Callers decide when to use it.
"""

import smtplib
from dataclasses import dataclass, field
from email.message import EmailMessage
from typing import Protocol


class EmailSender(Protocol):
    """Something that can send a plain-text email."""

    def send(self, to: str, subject: str, body: str) -> None:
        """Send a plain-text email to `to`."""
        ...


@dataclass(frozen=True, slots=True)
class SmtpEmailSender:
    """Sends email over SMTP, optionally with STARTTLS and authentication."""

    host: str
    port: int
    sender: str
    use_tls: bool = True
    username: str | None = None
    password: str | None = None

    def send(self, to: str, subject: str, body: str) -> None:
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = to
        message["Subject"] = subject
        message.set_content(body)

        with smtplib.SMTP(self.host, self.port) as smtp:
            if self.use_tls:
                smtp.starttls()
            if self.username is not None:
                smtp.login(self.username, self.password or "")
            smtp.send_message(message)


@dataclass(frozen=True, slots=True)
class SentEmail:
    """A record of one message handed to a `FakeEmailSender`."""

    to: str
    subject: str
    body: str


@dataclass
class FakeEmailSender:
    """Records sent messages instead of delivering them, for tests."""

    sent: list[SentEmail] = field(default_factory=list)

    def send(self, to: str, subject: str, body: str) -> None:
        self.sent.append(SentEmail(to=to, subject=subject, body=body))
