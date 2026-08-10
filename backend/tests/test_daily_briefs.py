from __future__ import annotations

import time

from fastapi.testclient import TestClient
from pmaa_web.main import app


def test_daily_brief_schedule_generation_and_read_state() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/daily-briefs/schedules",
            json={
                "name": "工作日晨报",
                "local_time": "08:30",
                "timezone": "Asia/Shanghai",
                "weekdays": [0, 1, 2, 3, 4],
                "topics": ["AI 与大模型", "Agentic RAG"],
                "include_email": False,
                "include_calendar": True,
                "include_memory": False,
            },
        )
        assert created.status_code == 201, created.text
        schedule = created.json()
        assert schedule["next_run_at"]

        updated = client.patch(
            f"/api/v1/daily-briefs/schedules/{schedule['id']}",
            json={"local_time": "09:00", "enabled": True},
        )
        assert updated.status_code == 200, updated.text
        assert updated.json()["local_time"] == "09:00"

        queued = client.post(
            "/api/v1/daily-briefs/generate",
            json={
                "schedule_id": schedule["id"],
                "topics": [],
                "include_email": False,
                "include_calendar": True,
                "include_memory": False,
            },
        )
        assert queued.status_code == 202, queued.text
        brief_id = queued.json()["id"]

        brief = queued.json()
        for _ in range(100):
            brief = client.get(f"/api/v1/daily-briefs/{brief_id}").json()
            if brief["status"] in {"completed", "failed"}:
                break
            time.sleep(0.03)
        assert brief["status"] == "completed", brief
        assert brief["sections"]["summary"]
        assert "联网搜索未配置" in " ".join(brief["sections"]["warnings"])
        run_id = brief["sections"]["run_id"]
        run = client.get(f"/api/v1/runs/{run_id}").json()
        assert run["status"] == "completed"
        assert run["result_payload"]["orchestration"]["assigned_agents"] == [
            "daily_brief"
        ]
        events = client.get(f"/api/v1/runs/{run_id}/events/history").json()
        assert [
            event["payload"].get("node")
            for event in events
            if event["agent_id"] == "daily_brief"
            and event["event_type"] == "agent_progress"
        ] == [
            "brief_analyze",
            "brief_collect",
            "brief_prioritize",
            "brief_compose",
        ]

        stats = client.get("/api/v1/daily-briefs/stats")
        assert stats.status_code == 200
        assert stats.json()["unread_count"] == 1
        assert stats.json()["active_schedule_count"] == 1

        read = client.post(f"/api/v1/daily-briefs/{brief_id}/read")
        assert read.status_code == 200
        assert read.json()["unread"] is False
        assert client.get("/api/v1/daily-briefs/stats").json()["unread_count"] == 0

        deleted = client.delete(f"/api/v1/daily-briefs/schedules/{schedule['id']}")
        assert deleted.status_code == 204


def test_daily_brief_rejects_invalid_weekdays() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/daily-briefs/schedules",
            json={"local_time": "08:00", "weekdays": [7]},
        )
        assert response.status_code == 422
