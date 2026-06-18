import logging

import httpx

from app.main import QueryStringRedactionFilter


def test_httpx_log_filter_removes_url_query_string() -> None:
    record = logging.LogRecord(
        name="httpx",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='HTTP Request: %s %s "%s %d %s"',
        args=(
            "GET",
            httpx.URL("https://api.opendota.com/api/teams?api_key=secret&limit=10"),
            "HTTP/1.1",
            200,
            "OK",
        ),
        exc_info=None,
    )

    QueryStringRedactionFilter().filter(record)

    message = record.getMessage()
    assert "https://api.opendota.com/api/teams" in message
    assert "api_key" not in message
    assert "secret" not in message
    assert "limit=10" not in message
