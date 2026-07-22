"""Small SQLite authority for management events, state, and command outcomes.

The JSONL ledger and ``current.json`` remain compatibility exports.  SQLite is
the transactional writer so one command cannot commit an event without its
current-state projection and terminal audit outcome.
"""

from __future__ import annotations

import copy
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .io import canonical_json
from .legacy.exports import load_v1_exports
from .reducer import empty_state, fold


SCHEMA_VERSION = 1


class DatabaseBusy(RuntimeError):
    """SQLite could not obtain the single management-writer transaction."""


class DatabaseIntegrityError(RuntimeError):
    """The transactional authority disagrees with its compatibility export."""


class StateDatabase:
    """Transactional state authority with JSON-compatible public records."""

    def __init__(self, path: Path, *, timeout: float = 5.0):
        self.path = path
        self.timeout = timeout

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=self.timeout,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = FULL")
        connection.execute(f"PRAGMA busy_timeout = {int(self.timeout * 1000)}")
        return connection

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            try:
                connection.execute("BEGIN IMMEDIATE")
            except sqlite3.OperationalError as exc:
                if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                    raise DatabaseBusy(
                        f"research state is busy after {self.timeout:.2f}s: {self.path}"
                    ) from exc
                raise
            yield connection
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()

    def initialize(
        self,
        *,
        legacy_events: list[dict[str, Any]] | None = None,
        legacy_audit: list[dict[str, Any]] | None = None,
    ) -> bool:
        """Create the authority and import an existing v1 JSONL ledger once."""
        created = not self.path.exists()
        connection = self._connect()
        try:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    seq INTEGER PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    command_id TEXT NOT NULL,
                    event_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS aggregates (
                    aggregate_type TEXT NOT NULL,
                    aggregate_id TEXT NOT NULL,
                    aggregate_version INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY (aggregate_type, aggregate_id)
                );
                CREATE TABLE IF NOT EXISTS command_receipts (
                    idempotency_key TEXT PRIMARY KEY,
                    input_sha256 TEXT NOT NULL,
                    event_id TEXT NOT NULL UNIQUE,
                    command_id TEXT NOT NULL,
                    FOREIGN KEY (event_id) REFERENCES events(event_id)
                );
                CREATE TABLE IF NOT EXISTS audit (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT,
                    audit_id TEXT NOT NULL UNIQUE,
                    command_id TEXT,
                    outcome TEXT NOT NULL,
                    audit_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS current_state (
                    singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                    source_seq INTEGER NOT NULL,
                    source_hash TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );
                """
            )
        finally:
            connection.close()
        with self.transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO metadata(key, value) VALUES('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            version = connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if version is None or int(version["value"]) != SCHEMA_VERSION:
                raise DatabaseIntegrityError(
                    f"unsupported state database schema: {version['value'] if version else None}"
                )
            event_count = int(
                connection.execute("SELECT COUNT(*) AS count FROM events").fetchone()[
                    "count"
                ]
            )
            if event_count == 0 and legacy_events:
                state = fold(legacy_events)
                for event in legacy_events:
                    self._insert_event(connection, event)
                    self._insert_receipt(connection, event)
                self._replace_state(connection, state)
            elif event_count == 0:
                self._replace_state(connection, empty_state())
            if created and legacy_audit:
                for row in legacy_audit:
                    self._insert_audit(connection, row, ignore_existing=True)
        return created

    @staticmethod
    def _insert_event(
        connection: sqlite3.Connection,
        event: dict[str, Any],
    ) -> None:
        connection.execute(
            """
            INSERT INTO events(seq, event_id, idempotency_key, command_id, event_json)
            VALUES(?, ?, ?, ?, ?)
            """,
            (
                int(event["seq"]),
                str(event["event_id"]),
                str(event["idempotency_key"]),
                str(event["command_id"]),
                canonical_json(event),
            ),
        )

    @staticmethod
    def _insert_receipt(
        connection: sqlite3.Connection,
        event: dict[str, Any],
    ) -> None:
        import hashlib

        command_input = {
            "event_type": event["event_type"],
            "aggregate_type": event["aggregate_type"],
            "aggregate_id": event["aggregate_id"],
            "payload": event["payload"],
        }
        digest = hashlib.sha256(
            canonical_json(command_input).encode("utf-8")
        ).hexdigest()
        connection.execute(
            """
            INSERT INTO command_receipts(
                idempotency_key, input_sha256, event_id, command_id
            ) VALUES(?, ?, ?, ?)
            """,
            (
                str(event["idempotency_key"]),
                digest,
                str(event["event_id"]),
                str(event["command_id"]),
            ),
        )

    @staticmethod
    def _insert_audit(
        connection: sqlite3.Connection,
        row: dict[str, Any],
        *,
        ignore_existing: bool = False,
    ) -> None:
        clause = "INSERT OR IGNORE" if ignore_existing else "INSERT"
        connection.execute(
            f"""
            {clause} INTO audit(audit_id, command_id, outcome, audit_json)
            VALUES(?, ?, ?, ?)
            """,
            (
                str(row["audit_id"]),
                row.get("command_id"),
                str(row["outcome"]),
                canonical_json(row),
            ),
        )

    @staticmethod
    def _replace_state(
        connection: sqlite3.Connection,
        state: dict[str, Any],
    ) -> None:
        connection.execute("DELETE FROM aggregates")
        versions = state.get("aggregate_versions", {})
        for aggregate_type, records in state.get("aggregates", {}).items():
            if not isinstance(records, dict):
                continue
            for aggregate_id, record in records.items():
                connection.execute(
                    """
                    INSERT INTO aggregates(
                        aggregate_type, aggregate_id, aggregate_version, record_json
                    ) VALUES(?, ?, ?, ?)
                    """,
                    (
                        str(aggregate_type),
                        str(aggregate_id),
                        int(versions.get(f"{aggregate_type}/{aggregate_id}", 0)),
                        canonical_json(record),
                    ),
                )
        connection.execute(
            """
            INSERT INTO current_state(singleton, source_seq, source_hash, state_json)
            VALUES(1, ?, ?, ?)
            ON CONFLICT(singleton) DO UPDATE SET
                source_seq=excluded.source_seq,
                source_hash=excluded.source_hash,
                state_json=excluded.state_json
            """,
            (
                int(state.get("source_seq", 0)),
                str(state.get("source_hash", "")),
                canonical_json(state),
            ),
        )

    def events(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT event_json FROM events ORDER BY seq"
            ).fetchall()
        return [json.loads(row["event_json"]) for row in rows]

    def event_by_idempotency_key(self, key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_json FROM events WHERE idempotency_key = ?",
                (key,),
            ).fetchone()
        return json.loads(row["event_json"]) if row else None

    def event_by_id(self, event_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_json FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return json.loads(row["event_json"]) if row else None

    def state(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state_json FROM current_state WHERE singleton = 1"
            ).fetchone()
        return json.loads(row["state_json"]) if row else empty_state()

    def audit(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT audit_json FROM audit ORDER BY seq"
            ).fetchall()
        return [json.loads(row["audit_json"]) for row in rows]

    def snapshot(
        self,
        *,
        include_audit: bool = False,
    ) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
        """Read state, ledger, and optional audit from one SQLite snapshot."""
        connection = self._connect()
        try:
            connection.execute("BEGIN")
            event_rows = connection.execute(
                "SELECT event_json FROM events ORDER BY seq"
            ).fetchall()
            state_row = connection.execute(
                "SELECT state_json FROM current_state WHERE singleton = 1"
            ).fetchone()
            audit_rows = (
                connection.execute(
                    "SELECT audit_json FROM audit ORDER BY seq"
                ).fetchall()
                if include_audit
                else []
            )
            connection.execute("COMMIT")
        finally:
            connection.close()
        state = json.loads(state_row["state_json"]) if state_row else empty_state()
        events = [json.loads(row["event_json"]) for row in event_rows]
        audit = [json.loads(row["audit_json"]) for row in audit_rows]
        return state, events, audit

    def apply_command(
        self,
        *,
        event: dict[str, Any],
        state: dict[str, Any],
        audit_row: dict[str, Any],
    ) -> None:
        with self.transaction() as connection:
            self._insert_event(connection, event)
            self._insert_receipt(connection, event)
            self._replace_state(connection, state)
            self._insert_audit(connection, audit_row)

    def append_audit(self, row: dict[str, Any]) -> None:
        with self.transaction() as connection:
            self._insert_audit(connection, row)

    def replace_state(self, state: dict[str, Any]) -> None:
        with self.transaction() as connection:
            self._replace_state(connection, state)

    def import_audit(self, row: dict[str, Any]) -> bool:
        with self.transaction() as connection:
            before = int(
                connection.execute("SELECT COUNT(*) AS count FROM audit").fetchone()[
                    "count"
                ]
            )
            self._insert_audit(connection, row, ignore_existing=True)
            after = int(
                connection.execute("SELECT COUNT(*) AS count FROM audit").fetchone()[
                    "count"
                ]
            )
        return after > before

    def verify(self) -> dict[str, Any]:
        events = self.events()
        replayed = fold(events)
        current = self.state()
        if replayed != current:
            raise DatabaseIntegrityError(
                "SQLite current_state does not equal a fold of its event ledger"
            )
        return copy.deepcopy(current)


def bootstrap_database(
    database: StateDatabase,
    *,
    events_path: Path,
    audit_path: Path,
) -> bool:
    events, audit = load_v1_exports(events_path, audit_path)
    return database.initialize(
        legacy_events=events,
        legacy_audit=audit,
    )
