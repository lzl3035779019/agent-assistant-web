from __future__ import annotations

from fastapi.testclient import TestClient
from pmaa_web.main import app


def _prepare(client: TestClient, action: str, payload: dict, target_id: str | None = None) -> dict:
    response = client.post(
        "/api/v1/calendar/actions",
        json={"action": action, "target_id": target_id, "payload": payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _confirm(client: TestClient, action_id: str) -> dict:
    response = client.post(f"/api/v1/calendar/actions/{action_id}/confirm")
    assert response.status_code == 200, response.text
    return response.json()


def test_calendar_action_confirmation_conflicts_and_stats() -> None:
    with TestClient(app) as client:
        prepared = _prepare(
            client,
            "event.create",
            {
                "title": "项目评审",
                "description": "讨论第一版交付",
                "location": "线上会议",
                "start_at": "2027-08-08T14:00:00+08:00",
                "end_at": "2027-08-08T15:00:00+08:00",
            },
        )
        assert prepared["status"] == "pending"
        assert client.get("/api/v1/calendar/events").json() == []

        executed = _confirm(client, prepared["id"])
        assert executed["status"] == "executed"
        event_id = executed["result_payload"]["target_id"]

        conflict = _prepare(
            client,
            "event.create",
            {
                "title": "冲突会议",
                "start_at": "2027-08-08T14:30:00+08:00",
                "end_at": "2027-08-08T15:30:00+08:00",
            },
        )
        assert conflict["result_payload"]["has_conflict"] is True
        assert conflict["result_payload"]["conflicts"][0]["id"] == event_id

        stats = client.get("/api/v1/calendar/stats")
        assert stats.status_code == 200
        assert stats.json()["upcoming_events"] == 1

        duplicate = client.post(f"/api/v1/calendar/actions/{prepared['id']}/confirm")
        assert duplicate.status_code == 409


def test_calendar_event_update_and_cancel_are_confirmed() -> None:
    with TestClient(app) as client:
        created = _confirm(
            client,
            _prepare(
                client,
                "event.create",
                {
                    "title": "原始标题",
                    "start_at": "2027-08-10T09:00:00+08:00",
                    "end_at": "2027-08-10T10:00:00+08:00",
                },
            )["id"],
        )
        event_id = created["result_payload"]["target_id"]

        updated = _prepare(
            client,
            "event.update",
            {
                "title": "修改后的标题",
                "start_at": "2027-08-10T10:00:00+08:00",
                "end_at": "2027-08-10T11:00:00+08:00",
            },
            event_id,
        )
        _confirm(client, updated["id"])
        events = client.get(
            "/api/v1/calendar/events?start_at=2027-08-10T00:00:00%2B08:00&end_at=2027-08-11T00:00:00%2B08:00"
        ).json()
        assert events[0]["title"] == "修改后的标题"

        cancelled = _prepare(client, "event.cancel", {}, event_id)
        _confirm(client, cancelled["id"])
        assert client.get(
            "/api/v1/calendar/events?start_at=2027-08-10T00:00:00%2B08:00&end_at=2027-08-11T00:00:00%2B08:00"
        ).json() == []


def test_todo_lifecycle_uses_the_same_action_protocol() -> None:
    with TestClient(app) as client:
        created = _confirm(
            client,
            _prepare(
                client,
                "todo.create",
                {
                    "title": "完善项目文档",
                    "description": "补充架构图",
                    "due_at": "2027-08-09T18:00:00+08:00",
                    "priority": 8,
                },
            )["id"],
        )
        todo_id = created["result_payload"]["target_id"]
        todos = client.get("/api/v1/calendar/todos").json()
        assert todos[0]["priority"] == 8

        completed = _prepare(
            client,
            "todo.update",
            {"status": "completed"},
            todo_id,
        )
        _confirm(client, completed["id"])
        assert client.get("/api/v1/calendar/todos").json() == []
        all_todos = client.get("/api/v1/calendar/todos?include_completed=true").json()
        assert all_todos[0]["status"] == "completed"
