from __future__ import annotations

from logto_management_skill import LogtoAPIError, LogtoClient


def test_doctor_unresolved_reference():
    client = LogtoClient("op://your-vault/your-item/endpoint", "app-id", "app-secret", tenant_id="your-tenant-id")
    assert client.doctor.run()["classification"] == "unresolved_credentials"


def test_doctor_missing_tenant_id():
    client = LogtoClient("https://example.com", "app-id", "app-secret")
    assert client.doctor.run()["classification"] == "missing_tenant_id"


def test_doctor_wrong_credentials(client):
    client._get_token = lambda: (_ for _ in ()).throw(LogtoAPIError(400, {"code": "invalid_client"}, "token"))
    assert client.doctor.run()["classification"] == "wrong_credentials"


def test_doctor_missing_role_and_healthy(client):
    client._get_token = lambda: "token"
    client.request.side_effect = LogtoAPIError(403, {"message": "Denied"}, "https://example.com/api/test")
    assert client.doctor.run()["classification"] == "missing_management_api_role"

    client.request.side_effect = None
    client.request.return_value = []
    assert client.doctor.run()["classification"] == "healthy"
