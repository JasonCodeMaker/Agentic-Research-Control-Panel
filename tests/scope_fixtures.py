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

TASK_SPEC = {
    "experiment": (
        "Run a baseline reproduction study that verifies the declared retrieval pipeline before "
        "any new method changes are evaluated in production."
    ),
    "config": "scope:dir/retrieval-v2#m0-baseline-validity",
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


def task_spec(**overrides):
    spec = copy.deepcopy(TASK_SPEC)
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


def task_node(node_id="task/retrieval-v2/M0-baseline-validity", *, parent="dir/retrieval-v2",
              version=1, status="ACTIVE", source="triage:m1", **spec_overrides):
    return {
        "id": node_id,
        "level": "task",
        "parents": [parent],
        "version": version,
        "status": status,
        "spec": task_spec(**spec_overrides),
        "source": source,
    }
