"""POST /attach — PDF/Word parsing for turn-scoped chat context.

Nothing here is persisted or embedded; these tests only check the extraction and
its failure modes, the same way test_api.py checks auth without a dataset.
"""
import io
import os

import pytest

os.environ.setdefault("VERITAS_DEV_MODE", "1")


def _auth(client, badge_no: str) -> dict:
    r = client.post("/auth/token", json={"badge_no": badge_no})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_attach_requires_a_token(client, dataset):
    r = client.post("/attach", files={"file": ("x.pdf", b"not a real pdf", "application/pdf")})
    assert r.status_code == 401


def test_attach_rejects_an_unsupported_extension(client, dataset, officers):
    headers = _auth(client, officers["IO"]["badge_no"])
    r = client.post("/attach", headers=headers,
                    files={"file": ("notes.txt", b"hello", "text/plain")})
    assert r.status_code == 400


def test_attach_rejects_an_unparseable_pdf(client, dataset, officers):
    headers = _auth(client, officers["IO"]["badge_no"])
    r = client.post("/attach", headers=headers,
                    files={"file": ("bad.pdf", b"this is not a pdf", "application/pdf")})
    assert r.status_code == 422


def test_attach_extracts_docx_text(client, dataset, officers):
    docx = pytest.importorskip("docx")
    doc = docx.Document()
    doc.add_paragraph("Statement of witness Ramesh regarding case 412.")
    buf = io.BytesIO()
    doc.save(buf)
    buf.seek(0)

    headers = _auth(client, officers["IO"]["badge_no"])
    r = client.post("/attach", headers=headers, files={
        "file": ("statement.docx", buf.read(),
                 "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Ramesh" in body["text"]
    assert body["filename"] == "statement.docx"
    assert body["truncated"] is False
