from __future__ import annotations

from unittest.mock import patch

import pytest

from conftest import response
from logto_management_skill import LogtoAPIError, LogtoClient


@patch("logto_management_skill.client.requests")
def test_request_parses_dict_list_empty_and_raw(requests):
    requests.post.return_value = response(data={"access_token": "token"})
    raw = response(data={"id": "object-id"})
    requests.request.side_effect = [raw, response(data=[{"id": "one"}]), response(status_code=204)]
    client = LogtoClient("tenant", "app-id", "app-secret")

    assert client.request("GET", "/api/object") == {"id": "object-id"}
    assert client.request("GET", "/api/list") == [{"id": "one"}]
    assert client.request("DELETE", "/api/object") is None

    requests.request.return_value = raw
    requests.request.side_effect = None
    assert client.request("GET", "/api/object", raw=True) is raw


@patch("logto_management_skill.client.requests")
def test_401_refreshes_once(requests):
    requests.post.return_value = response(data={"access_token": "token"})
    requests.request.side_effect = [response(401, {"message": "expired"}), response(data=[])]
    client = LogtoClient("tenant", "app-id", "app-secret")

    assert client.request("GET", "/api/roles") == []
    assert requests.post.call_count == 2


@patch("logto_management_skill.client.requests")
def test_error_preserves_structured_fields(requests):
    requests.post.return_value = response(data={"access_token": "token"})
    requests.request.return_value = response(400, {"code": "user.same_password", "message": "Same password"})
    client = LogtoClient("tenant", "app-id", "app-secret")

    with pytest.raises(LogtoAPIError) as caught:
        client.request("POST", "/api/users", json={})
    error = caught.value
    assert error.status_code == 400
    assert error.code == "user.same_password"
    assert error.message == "Same password"
    assert error.body["code"] == "user.same_password"
    assert error.url == "https://example.com/api/test"


def test_custom_domain_requires_tenant_id_with_console_guidance():
    client = LogtoClient("https://example.com", "app-id", "app-secret")
    with pytest.raises(LogtoAPIError, match="Management API indicator"):
        client._get_token()


@patch("logto_management_skill.client.requests")
def test_logto_domain_derives_resource_and_from_env(requests, monkeypatch):
    requests.post.return_value = response(data={"access_token": "token"})
    client = LogtoClient("your-tenant-id", "app-id", "app-secret")
    client._get_token()
    assert requests.post.call_args.kwargs["data"]["resource"] == "https://your-tenant-id.logto.app/api"

    monkeypatch.setenv("LOGTO_ENDPOINT", "your-tenant-id")
    monkeypatch.setenv("LOGTO_APP_ID", "app-id")
    monkeypatch.setenv("LOGTO_APP_SECRET", "app-secret")
    assert isinstance(LogtoClient.from_env(), LogtoClient)


def test_all_cli_namespaces_exist():
    client = LogtoClient("tenant", "app-id", "app-secret")
    for name in (
        "users", "roles", "apps", "resources", "sign_in_exp", "account_center",
        "email_templates", "user_mfa", "orgs", "snapshot", "api", "doctor",
    ):
        assert getattr(client, name) is not None


def test_api_error_code_is_none_when_payload_has_no_code():
    error = LogtoAPIError(500, {"message": "Failure"}, "https://example.com/api/test")
    assert error.code is None
