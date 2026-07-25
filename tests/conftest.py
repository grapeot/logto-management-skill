from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from logto_management_skill import LogtoClient


FIXTURES = Path(__file__).parent / "fixtures"


def response(status_code: int = 200, data=None, text: str | None = None):
    result = MagicMock()
    result.status_code = status_code
    result.ok = 200 <= status_code < 300
    result.url = "https://example.com/api/test"
    result.text = text if text is not None else (json.dumps(data) if data is not None else "")
    result.json.return_value = data
    result.headers = {}
    return result


@pytest.fixture
def client(tmp_path):
    result = LogtoClient(
        "https://example.com",
        "app-id",
        "app-secret",
        tenant_id="your-tenant-id",
        backup_dir=str(tmp_path / "backups"),
    )
    result.request = MagicMock()
    result._guarded_request = result.request
    return result


@pytest.fixture
def swagger():
    return json.loads((FIXTURES / "swagger.json").read_text())


@pytest.fixture
def connector():
    return json.loads((FIXTURES / "connector.json").read_text())
