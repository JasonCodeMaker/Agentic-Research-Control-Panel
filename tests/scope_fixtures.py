import copy


PROJECT_SPEC = {
    "goal": (
        "Build an auditable research workflow that keeps project intent, package execution, "
        "evidence review, and user decisions aligned across repeated experiments."
    ),
    "contributions": [
        "Maintain a typed Scope log for ratified research intent.",
        "Project accepted Directions into packages with traceable provenance.",
    ],
    "out_of_scope": [
        "Do not automate paper writing or claim adoption without evidence.",
    ],
}

DIRECTION_SPEC = {
    "hypothesis": (
        "Adding supervised contrastive pretraining before retrieval fine tuning will improve "
        "zero shot ranking stability without changing the evaluation corpus or data budget."
    ),
    "metric": {"name": "Recall@10", "dir": "higher"},
    "baselines": [
        "CLIP zero shot retrieval baseline on the same held out split.",
    ],
    "success_gate": (
        "Recall at ten must improve by at least two absolute points over the declared baseline "
        "on the held out evaluation split."
    ),
}

EXPERIMENT_SPEC = {
    "purpose": (
        "Run a baseline reproduction study that verifies the declared retrieval pipeline before "
        "any new method changes are evaluated in production."
    ),
    "config_ref": "configs/m0-baseline-validity.yaml",
    "gate": (
        "The reproduced baseline metric must fall within the accepted tolerance window before "
        "downstream experiments can compare new method variants fairly."
    ),
    "control_mode": "CHECKPOINTED",
}


def project_spec(**overrides):
    spec = copy.deepcopy(PROJECT_SPEC)
    spec.update(overrides)
    return spec


def direction_spec(**overrides):
    spec = copy.deepcopy(DIRECTION_SPEC)
    spec.update(overrides)
    return spec


def experiment_spec(**overrides):
    spec = copy.deepcopy(EXPERIMENT_SPEC)
    spec.update(overrides)
    return spec


def project_node(node_id="project/main", *, version=1, status="ACTIVE", source="triage:p1", **spec_overrides):
    return {
        "id": node_id,
        "level": "project",
        "parents": [],
        "version": version,
        "status": status,
        "spec": project_spec(**spec_overrides),
        "source": source,
    }


def direction_node(node_id="dir/retrieval-v2", *, parent="project/main",
                   version=1, status="ACTIVE", source="triage:t1", **spec_overrides):
    return {
        "id": node_id,
        "level": "direction",
        "parents": [parent],
        "version": version,
        "status": status,
        "spec": direction_spec(**spec_overrides),
        "source": source,
    }


def experiment_node(
    node_id="experiment/retrieval-v2/M0-baseline-validity",
    *,
    parent="dir/retrieval-v2",
    version=1,
    status="ACTIVE",
    source="triage:m1",
    **spec_overrides,
):
    return {
        "id": node_id,
        "level": "experiment",
        "parents": [parent],
        "version": version,
        "status": status,
        "spec": experiment_spec(**spec_overrides),
        "source": source,
    }


def proposal_item(
    node,
    *,
    op="create",
    gate=None,
    proposal_id=None,
    invalidates=None,
    reopens=None,
    dial_revert=None,
):
    required_gate = {
        "project": "USER_ONLY",
        "direction": "USER_CROSS_MODEL_AUDIT",
        "experiment": "AGENT_DEFERRED_ACK",
    }[node["level"]]
    item = {
        "id": proposal_id or (
            f"proposal-{node['level']}-{node['id'].replace('/', '-')}-v{node['version']}"
        ),
        "level": node["level"],
        "node_id": node["id"],
        "op": op,
        "gate": gate or required_gate,
        "change": f"{op} {node['id']}",
        "rationale": "Test fixture for a hash-bound accepted Scope transition.",
        "proposed_spec": copy.deepcopy(node["spec"]),
        "proposed_node": copy.deepcopy(node),
        "invalidates": list(invalidates or []),
        "reopens": list(reopens or []),
        "dial_revert": list(dial_revert or []),
        "post_accept_actions": [],
    }
    return item


def commit_accepted_scope(
    management,
    paths,
    node,
    *,
    op="create",
    gate=None,
    proposal_id=None,
    invalidates=None,
    reopens=None,
    dial_revert=None,
    actor=None,
):
    item = proposal_item(
        node,
        op=op,
        gate=gate,
        proposal_id=proposal_id,
        invalidates=invalidates,
        reopens=reopens,
        dial_revert=dial_revert,
    )
    management.submit_proposal(paths, item, actor=actor)
    proposal = management.pending_proposals(paths)[-1]
    management.dispose_proposal(
        paths,
        item["id"],
        "ACCEPTED",
        proposal["proposal_hash"],
        actor={"type": "user", "id": "test-pm"},
    )
    payload, causation_id = management.accepted_scope_payload(paths, item["id"])
    return management.commit_scope_transition(
        paths,
        payload,
        actor=actor,
        causation_id=causation_id,
    )
