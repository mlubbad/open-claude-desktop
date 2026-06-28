def test_models_have_expected_columns():
    from ocd_core.db.models import Project, Conversation
    assert set(Project.model_fields) >= {
        "id", "name", "instructions", "memory", "allowlist", "created_at", "updated_at"}
    assert set(Conversation.model_fields) >= {
        "id", "project_id", "title", "pinned", "transcript", "created_at", "updated_at"}
