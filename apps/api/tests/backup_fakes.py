"""A mailer that records instead of sending, and can be told to fail."""

import re
from dataclasses import dataclass, field

from app.modules.backup.mailer import MailError, OutgoingEmail

TOKEN_IN_LINK = re.compile(r"token=([A-Za-z0-9_-]+)")


@dataclass
class RecordingMailer:
    sent: list[OutgoingEmail] = field(default_factory=list)
    # Consumed one per attempt: an Arabic reason fails that attempt, None
    # lets it through. When empty, ``always_fail`` (if set) fails every attempt.
    failures: list[str | None] = field(default_factory=list)
    always_fail: str | None = None
    attempts: int = 0

    async def send(self, message: OutgoingEmail) -> None:
        self.attempts += 1
        reason = self.failures.pop(0) if self.failures else self.always_fail
        if reason is not None:
            raise MailError(reason)
        self.sent.append(message)

    def last_token(self) -> str:
        match = TOKEN_IN_LINK.search(self.sent[-1].body)
        assert match, self.sent[-1].body
        return match.group(1)
