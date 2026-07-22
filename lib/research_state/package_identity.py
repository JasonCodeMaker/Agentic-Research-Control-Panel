"""Canonical Package identity helpers.

The semantic title is designed by the agent from the Package's core purpose.
This module validates its mechanical representation; it does not attempt to
infer research intent from prose.
"""

from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any


IDENTITY_CONTRACT_VERSION = 1
_TITLE_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")


class PackageIdentityViolation(ValueError):
    """A Package identity does not satisfy the canonical contract."""


def validate_title(title: str) -> str:
    """Validate one agent-designed, case-preserving title stem."""
    if not isinstance(title, str) or title != title.strip() or not title:
        raise PackageIdentityViolation("Package title must be a non-empty trimmed string")
    if len(title) > 96:
        raise PackageIdentityViolation("Package title must be at most 96 characters")
    if _TITLE_RE.fullmatch(title) is None:
        raise PackageIdentityViolation(
            "Package title must use hyphen-separated ASCII alphanumeric tokens"
        )
    return title


def validate_identity_date(value: str) -> str:
    """Validate the immutable date prefix used by a Package id."""
    if not isinstance(value, str):
        raise PackageIdentityViolation("Package identity date must be a string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise PackageIdentityViolation(
            "Package identity date must use a real YYYY-MM-DD date"
        ) from exc
    return parsed.isoformat()


def package_id(title: str, identity_date: str) -> str:
    """Return the only valid id for a canonical title and date."""
    return f"{validate_identity_date(identity_date)}-{validate_title(title)}"


def canonical_fields(
    *,
    title: str,
    identity_date: str,
    rationale: str,
) -> dict[str, Any]:
    """Build the fields shared by every canonical Package identity."""
    normalized_title = validate_title(title)
    normalized_date = validate_identity_date(identity_date)
    if not isinstance(rationale, str) or not rationale.strip():
        raise PackageIdentityViolation(
            "Package identity requires the agent's core-purpose rationale"
        )
    resolved_id = package_id(normalized_title, normalized_date)
    return {
        "id": resolved_id,
        "slug": resolved_id,
        "name": normalized_title,
        "title": normalized_title,
        "identityContractVersion": IDENTITY_CONTRACT_VERSION,
        "identityDate": normalized_date,
        "identityRationale": rationale.strip(),
    }


def validate_record(record: dict[str, Any]) -> None:
    """Validate canonical identity fields when a record opts into v1."""
    version = record.get("identityContractVersion")
    if version is None:
        return
    if version != IDENTITY_CONTRACT_VERSION:
        raise PackageIdentityViolation(
            f"unsupported Package identity contract version: {version!r}"
        )
    expected = canonical_fields(
        title=record.get("title"),
        identity_date=record.get("identityDate"),
        rationale=record.get("identityRationale"),
    )
    for field, value in expected.items():
        if record.get(field) != value:
            raise PackageIdentityViolation(
                f"Package identity field {field} must equal {value!r}"
            )


def renamed_record(
    record: dict[str, Any],
    *,
    title: str,
    identity_date: str,
    rationale: str,
) -> dict[str, Any]:
    """Return a Package record with canonical identity and audit history."""
    updated = copy.deepcopy(record)
    history = copy.deepcopy(updated.get("identityHistory") or [])
    if not isinstance(history, list):
        raise PackageIdentityViolation("Package identityHistory must be an array")
    history.append(
        {
            "id": str(record.get("id") or ""),
            "name": str(record.get("name") or ""),
            "title": str(record.get("title") or ""),
            "reason": rationale.strip(),
        }
    )
    updated.update(
        canonical_fields(
            title=title,
            identity_date=identity_date,
            rationale=rationale,
        )
    )
    updated["identityHistory"] = history
    return updated
