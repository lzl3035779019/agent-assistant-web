from pmaa_web.config import Settings


def test_local_chinese_embedding_defaults_are_dimensionally_consistent() -> None:
    settings = Settings(_env_file=None)

    assert settings.embedding_provider == "fastembed"
    assert settings.embedding_model == "BAAI/bge-small-zh-v1.5"
    assert settings.embedding_dimensions == 512


def test_reserved_integrations_are_disabled_by_default() -> None:
    settings = Settings(_env_file=None)

    assert settings.email_enabled is False
    assert settings.github_monitor_enabled is False
    assert settings.feishu_calendar_enabled is False
    assert settings.automation_scheduler_enabled is False
