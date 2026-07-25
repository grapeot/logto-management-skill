from __future__ import annotations


def test_search_matches_method_path_and_summary(client, swagger):
    client.request.return_value = swagger
    assert client.api.search("mfa")[0]["path"] == "/api/users/{userId}/mfa-verifications"
    assert client.api.search("patch")[0]["path"] == "/api/sign-in-exp"
    assert client.api.search("experience")[0]["method"] == "PATCH"
    client.request.assert_called_once_with("GET", "/api/swagger.json")


def test_schema_resolves_local_references(client, swagger):
    client.request.return_value = swagger
    schema = client.api.schema("PATCH", "/api/sign-in-exp")
    assert schema["request_body"]["content"]["application/json"]["schema"]["properties"]["mfa"] == {"type": "object"}


def test_non_get_call_is_dry_run_and_never_calls_request(client):
    result = client.api.call("PATCH", "/api/account-center", json={"enabled": True})
    assert result["dry_run"] is True
    assert client.request.call_args_list == []


def test_api_call_execute_and_get(client):
    client.request.side_effect = [{"ok": True}, [{"id": "role-id"}]]
    assert client.api.call("PATCH", "/api/account-center", json={"enabled": True}, execute=True) == {"ok": True}
    assert client.api.call("GET", "/api/roles") == [{"id": "role-id"}]
