from __future__ import annotations

import time

from fastapi.testclient import TestClient
from pmaa_web.main import app


def test_memory_crud_filters_and_stats() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/memories",
            json={"memory_type": "preference", "content": "用户喜欢跑步。"},
        )
        assert created.status_code == 201
        memory_id = created.json()["id"]

        duplicate = client.post(
            "/api/v1/memories",
            json={"memory_type": "preference", "content": "用户喜欢跑步。"},
        )
        assert duplicate.status_code == 409

        stats = client.get("/api/v1/memories/stats")
        assert stats.status_code == 200
        assert stats.json() == {
            "total": 1,
            "enabled": 1,
            "disabled": 0,
            "by_type": {"preference": 1},
        }

        disabled = client.patch(f"/api/v1/memories/{memory_id}", json={"enabled": False})
        assert disabled.status_code == 200
        assert disabled.json()["enabled"] is False

        filtered = client.get("/api/v1/memories?enabled=false&query=跑步")
        assert filtered.status_code == 200
        assert [item["id"] for item in filtered.json()] == [memory_id]

        deleted = client.delete(f"/api/v1/memories/{memory_id}")
        assert deleted.status_code == 204
        assert client.get("/api/v1/memories").json() == []


def test_run_extracts_memory_and_emits_memory_events() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            json={
                "objective": "我叫小林，我喜欢跑步、打游戏和旅游，请记住",
                "run_type": "assistant",
            },
        )
        assert response.status_code == 202
        run_id = response.json()["id"]

        run = response.json()
        for _ in range(150):
            run = client.get(f"/api/v1/runs/{run_id}").json()
            if run["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)
        assert run["status"] == "completed", run["error"]

        memories = client.get("/api/v1/memories").json()
        assert {(item["memory_type"], item["content"]) for item in memories} == {
            ("profile", "用户的名字是小林。"),
            ("preference", "用户喜欢跑步、打游戏和旅游。"),
        }

        events = client.get(f"/api/v1/runs/{run_id}/events/history").json()
        memory_progress = [
            event["payload"].get("node")
            for event in events
            if event["agent_id"] == "memory" and event["event_type"] == "agent_progress"
        ]
        assert memory_progress == [
            "memory_retrieve",
            "memory_extract",
            "memory_validate",
            "memory_update",
        ]
        completed = next(
            event
            for event in events
            if event["event_type"] == "agent_completed"
            and event["agent_id"] == "memory"
            and event["payload"].get("operation") == "maintain"
        )
        assert completed["payload"]["metrics"]["saved_count"] == 2
