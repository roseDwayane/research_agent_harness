from __future__ import annotations

import io
import json

from evaluation.step08.download import FILES, download, verify_download


class Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


def test_download_pins_revision_and_verifies_files(tmp_path):
    commit = "a" * 40
    payloads = {name: f"contents of {name}\n".encode() for name in FILES}
    calls = []

    def opener(request, timeout):
        calls.append((request.full_url, timeout))
        if "/api/datasets/" in request.full_url:
            return Response(json.dumps({"sha": commit}).encode())
        name = next(name for name in FILES if f"/{name}?" in request.full_url)
        return Response(payloads[name])

    manifest = download(tmp_path, opener=opener, say=lambda _message: None)
    assert manifest["resolved_revision"] == commit
    assert all((tmp_path / name).read_bytes() == payloads[name] for name in FILES)
    assert verify_download(tmp_path)["resolved_revision"] == commit
    assert len(calls) == 1 + len(FILES)

    # An intact manifest is reused without another network request.
    download(tmp_path, opener=lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("network used")),
             say=lambda _message: None)
