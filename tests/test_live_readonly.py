from __future__ import annotations

import os

import pytest

from logto_management_skill import LogtoClient


pytestmark = [
    pytest.mark.live_integration,
    pytest.mark.skipif(
        os.environ.get("LOGTO_LIVE_TESTS") != "1",
        reason="Set LOGTO_LIVE_TESTS=1 to run read-only live tests",
    ),
]


def test_live_swagger_search_is_read_only():
    client = LogtoClient.from_env()
    assert isinstance(client.api.search("user"), list)


def test_live_doctor_uses_read_only_probes():
    client = LogtoClient.from_env()
    assert client.doctor.run()["ok"] is True
