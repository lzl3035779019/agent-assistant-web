from __future__ import annotations

from fastapi.testclient import TestClient
from pmaa_web.main import app


def test_monitor_rule_crud_and_stats() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/monitors/rules",
            json={
                "name": "热门 AI 项目",
                "target_type": "github",
                "query": "topic:artificial-intelligence stars:>5000",
                "interval_minutes": 360,
                "enabled": True,
            },
        )
        assert created.status_code == 201, created.text
        rule = created.json()
        assert rule["next_run_at"]
        assert rule["last_run_status"] == "never"

        stats = client.get("/api/v1/monitors/stats")
        assert stats.status_code == 200
        assert stats.json() == {
            "rule_count": 1,
            "enabled_count": 1,
            "unread_count": 0,
            "running_count": 0,
        }

        updated = client.patch(
            f"/api/v1/monitors/rules/{rule['id']}",
            json={"name": "AI 开源项目", "enabled": False},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["name"] == "AI 开源项目"
        assert updated.json()["next_run_at"] is None

        listed = client.get("/api/v1/monitors/rules")
        assert listed.status_code == 200
        assert [item["id"] for item in listed.json()] == [rule["id"]]

        deleted = client.delete(f"/api/v1/monitors/rules/{rule['id']}")
        assert deleted.status_code == 204
        assert client.get("/api/v1/monitors/stats").json()["rule_count"] == 0


def test_monitor_rule_validation() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/monitors/rules",
            json={
                "name": "Too frequent",
                "target_type": "news",
                "query": "AI",
                "interval_minutes": 5,
            },
        )
        assert response.status_code == 422
