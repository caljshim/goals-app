from app.config import get_settings


def test_api_key_protects_api_but_leaves_health_public(client, monkeypatch):
    monkeypatch.setenv("APP_API_KEY", "test-key-with-enough-randomness")
    get_settings.cache_clear()
    try:
        assert client.get("/api/health").status_code == 200

        missing = client.get("/api/accounts")
        assert missing.status_code == 401
        assert missing.json()["detail"] == "Invalid or missing API key"

        wrong = client.get(
            "/api/accounts", headers={"Authorization": "Bearer definitely-wrong"}
        )
        assert wrong.status_code == 401

        accepted = client.get(
            "/api/accounts",
            headers={"Authorization": "Bearer test-key-with-enough-randomness"},
        )
        assert accepted.status_code == 200
    finally:
        get_settings.cache_clear()
