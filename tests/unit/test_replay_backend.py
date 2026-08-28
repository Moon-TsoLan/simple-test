from __future__ import annotations

import json

import pytest

from src.agents.backends import ReplayBackend


def test_replay_backend_loads_request_keyed_outputs(tmp_path) -> None:
    path = tmp_path / "responses.json"
    path.write_text(json.dumps({"responses": {"N:req_001": {"items": [], "warnings": []}}}), encoding="utf-8")
    backend = ReplayBackend.from_file(path)
    response = backend.complete(request_id="N:req_001")
    assert response.output == {"items": [], "warnings": []}
    assert response.raw_metadata["source"] == "offline_replay"
    with pytest.raises(KeyError):
        backend.complete(request_id="missing")
