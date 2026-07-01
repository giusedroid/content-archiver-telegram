from __future__ import annotations

import logging

from content_archiver_telegram.cli import _SecretRedactionFilter


def test_secret_redaction_filter_replaces_token() -> None:
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="POST https://api.telegram.org/botsecret-token/getMe",
        args=(),
        exc_info=None,
    )

    assert _SecretRedactionFilter(["secret-token"]).filter(record) is True
    assert record.getMessage() == "POST https://api.telegram.org/bot***/getMe"
