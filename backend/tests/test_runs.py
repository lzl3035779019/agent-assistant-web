from __future__ import annotations

import time

from fastapi.testclient import TestClient
from pmaa_web.main import app


def test_run_executes_and_persists_ordered_events() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            json={"objective": "验证 Agent 任务事件链", "run_type": "assistant"},
        )
        assert response.status_code == 202
        run_id = response.json()["id"]

        run = response.json()
        for _ in range(100):
            run = client.get(f"/api/v1/runs/{run_id}").json()
            if run["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)

        assert run["status"] == "completed", run["error"]
        history = client.get(f"/api/v1/runs/{run_id}/events/history")
        assert history.status_code == 200
        events = history.json()
        assert [event["sequence"] for event in events] == list(range(1, len(events) + 1))
        event_types = [event["event_type"] for event in events]
        assert event_types[0] == "run_started"
        assert event_types[-1] == "run_completed"
        assert event_types.count("agent_message") == 4
        assert "supervisor_decision" in event_types
        memory_nodes = [
            event["payload"].get("node")
            for event in events
            if event["agent_id"] == "memory" and event["event_type"] == "agent_progress"
        ]
        assert memory_nodes == [
            "memory_retrieve",
            "memory_extract",
            "memory_validate",
            "memory_update",
        ]


def test_agentic_rag_events_include_auditable_stage_details(monkeypatch) -> None:
    async def fake_retrieve(*args, **kwargs):
        return [
            {
                "chunk_id": "chunk-1",
                "document_id": "document-1",
                "filename": "architecture.md",
                "content": "Supervisor 负责委派专业 Agent。",
                "citation_id": "S1",
                "score": 0.88,
            }
        ]

    async def fake_answer(query, evidence):
        return "Supervisor 负责统一委派与结果聚合。[S1]"

    monkeypatch.setattr("pmaa_web.run_service.retrieve_evidence", fake_retrieve)
    monkeypatch.setattr("pmaa_web.run_service.generate_grounded_answer", fake_answer)

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            json={"objective": "多智能体架构包括什么", "run_type": "agentic_rag"},
        )
        assert response.status_code == 202
        run_id = response.json()["id"]

        run = response.json()
        for _ in range(100):
            run = client.get(f"/api/v1/runs/{run_id}").json()
            if run["status"] in {"completed", "failed"}:
                break
            time.sleep(0.02)

        assert run["status"] == "completed", run["error"]
        events = client.get(f"/api/v1/runs/{run_id}/events/history").json()
        assert next(
            event for event in events if event["event_type"] == "supervisor_decision"
        )["agent_id"] == "supervisor"
        progress = [
            event
            for event in events
            if event["event_type"] == "agent_progress"
            and event["agent_id"] == "knowledge"
        ]
        assert [event["payload"]["node"] for event in progress] == [
            "analyze",
            "retrieve",
            "grade",
            "synthesize",
        ]
        assert all(event["payload"]["title"] for event in progress)
        assert all("duration_ms" in event["payload"] for event in progress)
        retrieve_event = next(event for event in progress if event["payload"]["node"] == "retrieve")
        assert retrieve_event["payload"]["metrics"]["evidence_count"] == 1


def test_messages_are_appended_to_a_persistent_conversation() -> None:
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/runs",
            json={"objective": "第一个问题", "run_type": "assistant"},
        )
        assert first.status_code == 202
        first_run = _wait_for_run(client, first.json()["id"])
        conversation_id = first_run["conversation_id"]
        assert conversation_id

        second = client.post(
            "/api/v1/runs",
            json={
                "objective": "继续问第二个问题",
                "run_type": "assistant",
                "conversation_id": conversation_id,
            },
        )
        assert second.status_code == 202
        _wait_for_run(client, second.json()["id"])

        conversation = client.get(f"/api/v1/conversations/{conversation_id}")
        assert conversation.status_code == 200
        payload = conversation.json()
        assert [message["role"] for message in payload["messages"]] == [
            "user",
            "assistant",
            "user",
            "assistant",
        ]
        assert payload["messages"][0]["content"] == "第一个问题"
        assert payload["messages"][2]["content"] == "继续问第二个问题"
        assert payload["latest_run_id"] == second.json()["id"]

        listed = client.get("/api/v1/conversations")
        assert listed.status_code == 200
        assert listed.json()[0]["id"] == conversation_id
        assert listed.json()[0]["message_count"] == 4


def test_conversation_can_be_renamed_and_deleted() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/runs",
            json={"objective": "用于测试会话管理", "run_type": "assistant"},
        )
        assert response.status_code == 202
        run = _wait_for_run(client, response.json()["id"])
        conversation_id = run["conversation_id"]

        renamed = client.patch(
            f"/api/v1/conversations/{conversation_id}",
            json={"title": "重命名后的会话"},
        )
        assert renamed.status_code == 200
        assert renamed.json()["title"] == "重命名后的会话"

        detail = client.get(f"/api/v1/conversations/{conversation_id}")
        assert detail.status_code == 200
        assert detail.json()["title"] == "重命名后的会话"

        deleted = client.delete(f"/api/v1/conversations/{conversation_id}")
        assert deleted.status_code == 204
        assert client.get(f"/api/v1/conversations/{conversation_id}").status_code == 404

        detached_run = client.get(f"/api/v1/runs/{run['id']}")
        assert detached_run.status_code == 200
        assert detached_run.json()["conversation_id"] is None


def test_run_creation_is_idempotent_and_listable(monkeypatch) -> None:
    async def skip_dispatch(run_id):
        return None

    monkeypatch.setattr("pmaa_web.api.runs.dispatch_run", skip_dispatch)
    headers = {"Idempotency-Key": "test-idempotency-key"}
    with TestClient(app) as client:
        first = client.post(
            "/api/v1/runs",
            headers=headers,
            json={"objective": "幂等任务", "run_type": "assistant"},
        )
        second = client.post(
            "/api/v1/runs",
            headers=headers,
            json={"objective": "这次请求不应创建新任务", "run_type": "assistant"},
        )
        assert first.status_code == 202
        assert second.status_code == 202
        assert second.json()["id"] == first.json()["id"]

        listed = client.get("/api/v1/runs?limit=10&offset=0")
        assert listed.status_code == 200
        assert listed.json()["total"] == 1
        assert listed.json()["items"][0]["idempotency_key"] == "test-idempotency-key"


def test_queued_run_can_be_cancelled_and_retried(monkeypatch) -> None:
    async def skip_dispatch(run_id):
        return None

    monkeypatch.setattr("pmaa_web.api.runs.dispatch_run", skip_dispatch)
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/runs",
            json={"objective": "需要取消的任务", "run_type": "assistant"},
        )
        assert created.status_code == 202
        run_id = created.json()["id"]

        cancelled = client.post(f"/api/v1/runs/{run_id}/cancel")
        assert cancelled.status_code == 200
        assert cancelled.json()["status"] == "cancelled"
        assert cancelled.json()["cancel_requested_at"]

        retried = client.post(f"/api/v1/runs/{run_id}/retry")
        assert retried.status_code == 202
        assert retried.json()["status"] == "queued"
        assert retried.json()["retry_of_run_id"] == run_id


def _wait_for_run(client: TestClient, run_id: str) -> dict:
    run: dict = {}
    for _ in range(100):
        run = client.get(f"/api/v1/runs/{run_id}").json()
        if run["status"] in {"completed", "failed"}:
            return run
        time.sleep(0.02)
    raise AssertionError(f"Run {run_id} did not finish: {run}")
