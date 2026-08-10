from __future__ import annotations

from pmaa_web.memory_service import MemoryCandidate, extract_candidates, validate_candidate


def test_extracts_explicit_profile_and_preference_without_duplicate_instruction() -> None:
    candidates = extract_candidates("我叫小林，我喜欢跑步、打游戏和旅游，请记住")

    assert [(item.memory_type, item.content) for item in candidates] == [
        ("profile", "用户的名字是小林。"),
        ("preference", "用户喜欢跑步、打游戏和旅游。"),
    ]


def test_extracts_standalone_long_term_instruction() -> None:
    candidates = extract_candidates("以后回答技术问题时先给结论，再解释原因")

    assert len(candidates) == 1
    assert candidates[0].memory_type == "instruction"
    assert candidates[0].content.startswith("用户长期指令：")


def test_validator_rejects_sensitive_and_transient_content() -> None:
    sensitive = MemoryCandidate("instruction", "用户长期指令：记住 API Key sk-secret", 0.95)
    transient = MemoryCandidate("project", "今天的天气是晴天", 0.95)

    assert validate_candidate(sensitive) == (False, "sensitive_content")
    assert validate_candidate(transient) == (False, "transient_information")
