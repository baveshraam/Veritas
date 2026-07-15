"""Fetch model weights from Catalyst File Store on cold start.

Why the weights are not baked into the image: AppSail's bundle creator unpacks a
deployment in a ~5GB scratch space that must hold the archive, its blobs, the staged
layer AND the assembled rootfs at once — measured empirically, that caps a deployable
image at ~1.3GB, and NLLB alone is 600MB. So the image ships the *code* (~0.9GB) and
the weights (~760MB) live in the project's own File Store, pulled once per container.

This is not a third-party runtime dependency — File Store is a Catalyst service inside
the same project, reached over the SDK's app authentication, exactly like the Data
Store. The rule the architecture keeps is "no runtime download from huggingface.co";
weights moving from one Catalyst service into a Catalyst container never leave the
platform.

Two disk facts shape the implementation:

  * The runtime disk is capped at 1024MB, and tar (756MB) + extraction (756MB) do not
    fit — so the tar is never written to disk. The File Store chunks are streamed
    end-to-end into `tarfile`'s streaming reader.
  * The weights were uploaded as 95MB chunks (`models.tar.part-aa`…) because File
    Store uploads are per-file requests; `_ChunkStream` splices them back into one
    byte stream.

Configuration (all baked into the deployed image's env; absent in local dev, where
`ensure_models()` is a no-op and the models load from the local HF cache instead):

  VERITAS_MODELS_DIR        where to extract (default /tmp/models — the tar's top
                            directory is `models/`, so extraction lands exactly there)
  VERITAS_MODELS_FOLDER_ID  File Store folder holding the chunks
  VERITAS_MODELS_FILE_IDS   comma-separated chunk file ids, in order
"""
import io
import logging
import os
import tarfile
import threading

log = logging.getLogger(__name__)

_LOCK = threading.Lock()
_DONE = False


class _ChunkStream(io.RawIOBase):
    """Read-only byte stream spliced from consecutive File Store file downloads."""

    def __init__(self, folder, file_ids):
        self._folder = folder
        self._pending = list(file_ids)
        self._chunks = iter(())
        self._buf = b""

    def readable(self):
        return True

    def _next_chunk(self):
        while True:
            nxt = next(self._chunks, None)
            if nxt is not None:
                return nxt
            if not self._pending:
                return None
            fid = self._pending.pop(0)
            resp = self._folder.get_file_stream(fid)
            self._chunks = resp.iter_content(chunk_size=1 << 20)

    def read(self, size=-1):
        if size is None or size < 0:
            parts = [self._buf]
            self._buf = b""
            while (c := self._next_chunk()) is not None:
                parts.append(c)
            return b"".join(parts)
        while len(self._buf) < size:
            c = self._next_chunk()
            if c is None:
                break
            self._buf += c
        out, self._buf = self._buf[:size], self._buf[size:]
        return out


def ensure_models() -> bool:
    """Idempotent, thread-safe. True if the model directory is ready.

    Called at the top of every lazy model loader (translation, ASR, embeddings) and
    once from the API's startup hook so the download happens while the container
    warms rather than on an officer's first query.
    """
    global _DONE
    if _DONE:
        return True
    with _LOCK:
        if _DONE:
            return True
        parent = os.path.dirname(os.getenv("VERITAS_MODELS_DIR", "/tmp/models")) or "/tmp"
        target = os.getenv("VERITAS_MODELS_DIR", "/tmp/models")
        marker = os.path.join(target, ".complete")
        if os.path.exists(marker):
            _DONE = True
            return True

        folder_id = os.getenv("VERITAS_MODELS_FOLDER_ID")
        file_ids = [s for s in os.getenv("VERITAS_MODELS_FILE_IDS", "").split(",") if s]
        if not folder_id or not file_ids:
            # Local dev: weights come from the local HF cache; nothing to fetch.
            return False

        try:
            # Shared with ds: in AppSail the SDK context comes from request headers the
            # API middleware captured, never from env — initialize() bare would fail here.
            from data.ds import catalyst_app
            folder = catalyst_app().filestore().folder(folder_id)
            log.info("fetching %d model chunks from File Store folder %s",
                     len(file_ids), folder_id)
            stream = _ChunkStream(folder, file_ids)
            with tarfile.open(fileobj=stream, mode="r|") as tf:
                tf.extractall(parent)          # the tar's top-level dir is models/
            open(marker, "w").close()
            _DONE = True
            log.info("model weights ready at %s", target)
            return True
        except Exception:
            log.exception("model fetch from File Store failed — model-backed "
                          "features will report unavailable")
            return False
