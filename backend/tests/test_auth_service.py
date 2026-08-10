from __future__ import annotations

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pmaa_web.auth_service import (
    AuthError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from pmaa_web.config import get_settings
from pmaa_web.main import app


def test_password_hash_and_token_types_are_verified() -> None:
    encoded = hash_password("strong-password")
    assert verify_password("strong-password", encoded)
    assert not verify_password("wrong-password", encoded)

    user_id = uuid4()
    access = create_access_token(user_id)
    refresh, _ = create_refresh_token(user_id)
    assert decode_token(access, expected_type="access")["sub"] == str(user_id)
    assert decode_token(refresh, expected_type="refresh")["sub"] == str(user_id)
    with pytest.raises(AuthError):
        decode_token(access, expected_type="refresh")


def test_authenticated_users_cannot_read_each_others_runs(monkeypatch) -> None:
    async def skip_dispatch(run_id):
        return None

    monkeypatch.setattr("pmaa_web.api.runs.dispatch_run", skip_dispatch)
    settings = get_settings()
    previous = settings.auth_enabled
    settings.auth_enabled = True
    try:
        with TestClient(app) as client:
            first = client.post(
                "/api/v1/auth/register",
                json={"email": "first@example.com", "password": "password-123"},
            )
            second = client.post(
                "/api/v1/auth/register",
                json={"email": "second@example.com", "password": "password-456"},
            )
            assert first.status_code == 201
            assert second.status_code == 201
            first_headers = {"Authorization": f"Bearer {first.json()['access_token']}"}
            second_headers = {"Authorization": f"Bearer {second.json()['access_token']}"}

            created = client.post(
                "/api/v1/runs",
                headers=first_headers,
                json={"objective": "用户一的私有任务", "run_type": "assistant"},
            )
            assert created.status_code == 202
            run_id = created.json()["id"]
            assert client.get(f"/api/v1/runs/{run_id}", headers=first_headers).status_code == 200
            assert client.get(f"/api/v1/runs/{run_id}", headers=second_headers).status_code == 404
            assert client.get("/api/v1/runs").status_code == 401
    finally:
        settings.auth_enabled = previous
