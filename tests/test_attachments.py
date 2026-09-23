"""Images pasted into the dashboard: upload, serve, and delivery as a file path."""

import struct
import zlib

from agent_swarm import attachments
from tests.test_server import client  # noqa: F401  (reuse the app fixture)


def png(color: int = 0) -> bytes:
    """A valid 1x1 PNG; `color` varies the bytes so hashes differ."""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"\x00" + bytes([color, 0, 0])
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def upload(client, data: bytes, content_type: str = "image/png"):
    return client.post("/attachments", content=data, headers={"content-type": content_type})


def register(client, pane="0:0.0"):
    r = client.post("/register", json={"tmux_pane": pane})
    assert r.status_code == 200
    return r.json()["user_id"]


def test_upload_stores_by_content_and_serves_the_image(client):
    r = upload(client, png())
    assert r.status_code == 200
    body = r.json()
    assert body["name"].endswith(".png") and body["url"] == f"/attachments/{body['name']}"
    assert body["path"].endswith(f"/attachments/{body['name']}")

    # The same bytes land on the same name.
    assert upload(client, png()).json()["name"] == body["name"]

    got = client.get(body["url"])
    assert got.status_code == 200
    assert got.headers["content-type"] == "image/png"
    assert got.headers["x-content-type-options"] == "nosniff"
    assert got.content == png()


def test_upload_trusts_bytes_not_the_claimed_type(client):
    # SVG can carry script; it is refused even when labelled as an image.
    svg = b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'
    assert upload(client, svg, "image/svg+xml").status_code == 415
    assert upload(client, b"", "image/png").status_code == 415
    # A real PNG is accepted whatever the client calls it.
    assert upload(client, png(), "application/octet-stream").status_code == 200


def test_upload_rejects_oversized_images(client, monkeypatch):
    monkeypatch.setattr(attachments, "MAX_BYTES", 16)
    assert upload(client, png()).status_code == 413


def test_unknown_or_malformed_attachment_names_are_404(client):
    assert client.get("/attachments/" + "0" * 64 + ".png").status_code == 404
    assert client.get("/attachments/..%2Fdb.sqlite").status_code == 404
    assert client.get("/attachments/notahash.png").status_code == 404


def test_owner_message_delivers_image_paths_and_records_them(client):
    user = register(client)
    first = upload(client, png(1)).json()
    second = upload(client, png(2)).json()

    r = client.post("/owner/send", json={
        "recipient": user, "content": "what is wrong here?",
        "attachments": [first["name"], second["name"]],
    })
    assert r.status_code == 200 and r.json()["ok"]

    delivered = client._calls[-1][1]
    assert "what is wrong here?" in delivered
    assert f"[attached image: {first['path']}]" in delivered
    assert f"[attached image: {second['path']}]" in delivered

    msg = client.get("/api/state").json()["messages"][-1]
    assert msg["content"] == "what is wrong here?"
    assert msg["attachments"] == [first["name"], second["name"]]


def test_owner_can_send_an_image_without_text(client):
    user = register(client)
    image = upload(client, png()).json()
    r = client.post("/owner/send", json={"recipient": user, "attachments": [image["name"]]})
    assert r.status_code == 200
    assert client._calls[-1][1].rstrip().endswith(f"[attached image: {image['path']}]")


def test_owner_send_needs_text_or_a_known_image(client):
    user = register(client)
    assert client.post("/owner/send", json={"recipient": user, "content": "  "}).status_code == 422
    r = client.post("/owner/send", json={
        "recipient": user, "content": "hi", "attachments": ["0" * 64 + ".png"],
    })
    assert r.status_code == 400
    assert client._calls == []


def test_messages_without_images_report_an_empty_list(client):
    user = register(client)
    client.post("/owner/send", json={"recipient": user, "content": "plain"})
    assert client.get("/api/state").json()["messages"][-1]["attachments"] == []
