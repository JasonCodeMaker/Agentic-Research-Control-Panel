from __future__ import annotations

import json

from lib.interface import build_interface
from lib.interface.serve import ensure_interface_current, interface_is_current
from lib.research_state import EventStore, ResearchPaths


def test_many_commits_can_collapse_into_one_requested_projection(tmp_path):
    paths = ResearchPaths.resolve(workspace=tmp_path, environ={})
    store = EventStore(paths)
    store.initialize()
    initial = build_interface(paths)
    assert initial.source_seq == 0

    for index in range(3):
        store.commit(
            event_type="BrainstormCreated",
            aggregate_type="brainstorm",
            aggregate_id=f"idea-{index}",
            payload={
                "record": {
                    "id": f"idea-{index}",
                    "title": f"Idea {index}",
                    "idea": "test lazy projection",
                    "status": "ACTIVE",
                }
            },
            actor={"type": "agent", "id": "test"},
            idempotency_key=f"idea-{index}",
        )

    marker_path = paths.interface / "data" / "projection.json"
    assert json.loads(marker_path.read_text(encoding="utf-8"))["source_seq"] == 0
    assert interface_is_current(paths) is False

    ensure_interface_current(paths)

    assert interface_is_current(paths) is True
    assert json.loads(marker_path.read_text(encoding="utf-8"))["source_seq"] == 3
