import base64
import io

from PIL import Image
from sqlalchemy import inspect

from app.copilot import router as copilot_router


def _png(width=80, height=40) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (width, height), "#e8c66a").save(output, "PNG")
    return output.getvalue()


def _upload(client):
    response = client.post(
        "/api/media",
        content=_png(),
        headers={
            "content-type": "image/png",
            "x-filename": "../planner.png",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_image_upload_is_normalized_and_retrievable(client, engine):
    asset = _upload(client)

    assert asset["filename"] == "planner.jpg"
    assert asset["media_type"] == "image/jpeg"
    assert (asset["width"], asset["height"]) == (80, 40)
    assert asset["byte_size"] > 0
    assert "data" not in asset
    assert "media_asset" in inspect(engine).get_table_names()

    content = client.get(f"/api/media/{asset['id']}/content")
    assert content.status_code == 200
    assert content.headers["content-type"] == "image/jpeg"
    with Image.open(io.BytesIO(content.content)) as image:
        assert image.format == "JPEG"
        assert image.size == (80, 40)
        assert image.getexif() == {}


def test_upload_rejects_non_images_and_soft_delete_removes_content(client):
    invalid = client.post(
        "/api/media",
        content=b"not an image",
        headers={"content-type": "image/png"},
    )
    assert invalid.status_code == 422

    asset = _upload(client)
    deleted = client.delete(f"/api/media/{asset['id']}")
    assert deleted.status_code == 204
    assert client.get(f"/api/media/{asset['id']}").status_code == 404
    assert client.get(f"/api/media/{asset['id']}/content").status_code == 404


def test_chat_materializes_image_before_text(
    client,
    monkeypatch,
):
    asset = _upload(client)
    seen = {}

    def fake_copilot(session, messages, timezone_name=None):
        seen["messages"] = messages
        seen["timezone"] = timezone_name
        return {
            "reply": "I can read the planner.",
            "actions": [],
            "refresh": False,
            "ui_actions": [],
        }

    monkeypatch.setattr(copilot_router, "run_copilot", fake_copilot)
    response = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Put the clear entries on my calendar.",
                    "attachment_ids": [asset["id"]],
                }
            ],
            "timezone": "America/Los_Angeles",
        },
    )

    assert response.status_code == 200, response.text
    blocks = seen["messages"][0]["content"]
    assert [block["type"] for block in blocks] == ["image", "text"]
    assert blocks[0]["source"]["media_type"] == "image/jpeg"
    assert base64.b64decode(blocks[0]["source"]["data"]).startswith(b"\xff\xd8")
    assert blocks[1]["text"] == "Put the clear entries on my calendar."


def test_chat_rejects_missing_or_assistant_owned_images(client):
    missing = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": "Analyze this.",
                    "attachment_ids": ["missing"],
                }
            ]
        },
    )
    assert missing.status_code == 404

    asset = _upload(client)
    assistant_image = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {
                    "role": "assistant",
                    "content": "Previous",
                    "attachment_ids": [asset["id"]],
                }
            ]
        },
    )
    assert assistant_image.status_code == 422


def test_chat_limits_total_image_occurrences(client):
    asset = _upload(client)
    response = client.post(
        "/api/assistant/chat",
        json={
            "messages": [
                {
                    "role": "user",
                    "content": f"Image {index}",
                    "attachment_ids": [asset["id"]],
                }
                for index in range(5)
            ]
        },
    )

    assert response.status_code == 422
    assert "at most 4 images" in response.json()["detail"]
