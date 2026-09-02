"""POST /attach — parse an uploaded PDF or Word document into plain text.

Turn-scoped only: the console folds the extracted text into the NEXT chat message
as context (like pasting text into the composer), the same way the rest of a
query is free text. Nothing here is persisted, embedded into the vector index, or
cited as evidence — an attachment is not a record, so it never earns a [n].
"""
import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from ..auth.jwt_auth import Officer, current_officer

router = APIRouter()

_MAX_BYTES = 15 * 1024 * 1024   # 15MB
_MAX_CHARS = 8_000               # well under vx_conversation_turn's 10,000-char text cap


def _pdf_text(data: bytes) -> str:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _docx_text(data: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


@router.post("/attach")
async def attach(file: UploadFile, officer: Officer = Depends(current_officer)):
    data = await file.read()
    if len(data) > _MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File is larger than 15MB")

    name = (file.filename or "").lower()
    try:
        if name.endswith(".pdf"):
            text = _pdf_text(data)
        elif name.endswith(".docx"):
            text = _docx_text(data)
        else:
            raise HTTPException(status.HTTP_400_BAD_REQUEST,
                                "Only PDF and Word (.docx) files are supported")
    except HTTPException:
        raise
    except Exception as e:                                     # noqa: BLE001
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            f"Could not read this file ({type(e).__name__})") from e

    text = text.strip()
    if not text:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "No extractable text was found in this file")
    return {"filename": file.filename, "text": text[:_MAX_CHARS], "truncated": len(text) > _MAX_CHARS}
