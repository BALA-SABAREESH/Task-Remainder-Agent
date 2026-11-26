from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, ValidationError

TaskPriority = Literal["high", "med", "low"]

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RECORDS_DIR = DATA_DIR / "records"
TASKS_FILE = DATA_DIR / "tasks.json"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def display_time_now() -> str:
    return datetime.now().strftime("%I:%M %p").lstrip("0")


class TaskMetadata(BaseModel):
    tags: list[str] = Field(default_factory=list)
    ai_notes: str = ""
    document_source: Optional[str] = None
    chunk_count: int = 0


class TaskRecord(BaseModel):
    id: str
    index: int
    task: str
    done: bool = False
    priority: TaskPriority = "med"
    added: str
    created_at: str
    completed_at: Optional[str] = None
    detail_file: str
    source: str = "command"
    metadata: TaskMetadata = Field(default_factory=TaskMetadata)


class TaskDetailFile(BaseModel):
    schema_version: str = "1.0.0"
    task_id: str
    task: str
    done: bool = False
    priority: TaskPriority = "med"
    added: str
    created_at: str
    completed_at: Optional[str] = None
    source: str = "command"
    document_chunks: list[str] = Field(default_factory=list)
    extracted_entities: list[str] = Field(default_factory=list)
    ai_notes: str = ""
    checksum: str = ""


class StoreStats(BaseModel):
    total: int = 0
    completed: int = 0
    pending: int = 0
    completion_rate: int = 0
    ai_score: str = "—"


class IntegrityMetadata(BaseModel):
    checksum: str = ""
    valid: bool = True
    last_validated_at: str = Field(default_factory=utc_now_iso)
    record_count: int = 0


class TaskStore(BaseModel):
    schema_version: str = "1.0.0"
    storage_engine: str = "local-json-dbms"
    updated_at: str = Field(default_factory=utc_now_iso)
    integrity: IntegrityMetadata = Field(default_factory=IntegrityMetadata)
    stats: StoreStats = Field(default_factory=StoreStats)
    activity: list[int] = Field(default_factory=lambda: [0, 0, 0, 0, 0, 0, 0])
    tasks: list[TaskRecord] = Field(default_factory=list)


class IntegrityReport(BaseModel):
    valid: bool
    repaired: bool = False
    issues: list[str] = Field(default_factory=list)
    checksum: str
    record_count: int
    orphan_files_removed: int = 0
    missing_records_recreated: int = 0


class LocalJsonTaskDBMS:
    """Thread-safe, atomic local JSON file DBMS for tasks and processed documents."""

    def __init__(self, data_dir: Path = DATA_DIR) -> None:
        self._lock = threading.RLock()
        self.data_dir = data_dir
        self.records_dir = data_dir / "records"
        self.tasks_file = data_dir / "tasks.json"
        self._ensure_dirs()
        self._ensure_store_initialized()

    def _ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.records_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _compute_ai_score(total: int, completed: int) -> str:
        if total == 0:
            return "—"
        pct = completed / total
        if pct >= 0.9:
            return "A+"
        if pct >= 0.7:
            return "A"
        if pct >= 0.5:
            return "B+"
        if pct >= 0.3:
            return "B"
        return "C"

    @staticmethod
    def _compute_store_checksum(tasks: list[TaskRecord], activity: list[int]) -> str:
        canonical_payload = {
            "tasks": [t.model_dump(mode="json") for t in tasks],
            "activity": activity,
        }
        serialized = json.dumps(canonical_payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _compute_detail_checksum(detail: TaskDetailFile) -> str:
        payload = detail.model_dump(mode="json", exclude={"checksum"})
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            prefix=f".{target.stem}_", suffix=".tmp", dir=str(target.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=False)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, target)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

    def _sync_derived_fields(self, store: TaskStore) -> TaskStore:
        for idx, task in enumerate(store.tasks, start=1):
            task.index = idx
            task.detail_file = f"data/records/{task.id}.json"

        if len(store.activity) != 7:
            store.activity = (store.activity + [0] * 7)[:7]

        total = len(store.tasks)
        completed = sum(1 for t in store.tasks if t.done)
        pending = total - completed
        rate = round((completed / total) * 100) if total else 0

        now_iso = utc_now_iso()
        store.stats = StoreStats(
            total=total,
            completed=completed,
            pending=pending,
            completion_rate=rate,
            ai_score=self._compute_ai_score(total, completed),
        )
        store.updated_at = now_iso
        store.integrity = IntegrityMetadata(
            checksum=self._compute_store_checksum(store.tasks, store.activity),
            valid=True,
            last_validated_at=now_iso,
            record_count=total,
        )
        return store

    def _write_detail_file(
        self,
        task: TaskRecord,
        document_chunks: Optional[list[str]] = None,
        extracted_entities: Optional[list[str]] = None,
    ) -> None:
        detail = TaskDetailFile(
            task_id=task.id,
            task=task.task,
            done=task.done,
            priority=task.priority,
            added=task.added,
            created_at=task.created_at,
            completed_at=task.completed_at,
            source=task.source,
            document_chunks=document_chunks or [],
            extracted_entities=extracted_entities or [],
            ai_notes=task.metadata.ai_notes,
        )
        detail.checksum = self._compute_detail_checksum(detail)
        self._atomic_write_json(self.records_dir / f"{task.id}.json", detail.model_dump(mode="json"))

    def _delete_detail_file(self, task_id: str) -> bool:
        path = self.records_dir / f"{task_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False

    def _save_store(self, store: TaskStore) -> TaskStore:
        synced = self._sync_derived_fields(store)
        self._atomic_write_json(self.tasks_file, synced.model_dump(mode="json"))
        return synced

    def _ensure_store_initialized(self) -> None:
        with self._lock:
            self._ensure_dirs()
            if not self.tasks_file.exists():
                self._save_store(TaskStore())

    def load_store(self) -> TaskStore:
        with self._lock:
            self._ensure_store_initialized()
            raw_text = self.tasks_file.read_text(encoding="utf-8")
            raw_data = json.loads(raw_text)
            return TaskStore.model_validate(raw_data)

    def validate_and_repair(self) -> tuple[TaskStore, IntegrityReport]:
        with self._lock:
            self._ensure_dirs()
            issues: list[str] = []
            repaired = False
            orphan_removed = 0
            recreated = 0

            if not self.tasks_file.exists():
                store = self._save_store(TaskStore())
                return store, IntegrityReport(
                    valid=True,
                    repaired=True,
                    issues=["Initialized missing data/tasks.json"],
                    checksum=store.integrity.checksum,
                    record_count=0,
                )

            try:
                raw_data = json.loads(self.tasks_file.read_text(encoding="utf-8"))
                store = TaskStore.model_validate(raw_data)
            except (json.JSONDecodeError, ValidationError) as exc:
                issues.append(f"Schema validation error repaired: {exc}")
                store = TaskStore()
                repaired = True

            expected_checksum = self._compute_store_checksum(store.tasks, store.activity)
            if store.integrity.checksum != expected_checksum:
                issues.append("Master tasks.json checksum mismatch detected and repaired")
                repaired = True

            # Verify indices & stats match
            for i, task in enumerate(store.tasks, start=1):
                if task.index != i:
                    issues.append(f"Task index mismatch at position {i} repaired")
                    repaired = True
                    break

            # Verify detail record files exist & validate their checksums
            valid_ids = {t.id for t in store.tasks}
            for task in store.tasks:
                rec_path = self.records_dir / f"{task.id}.json"
                if not rec_path.exists():
                    self._write_detail_file(task)
                    issues.append(f"Recreated missing detail JSON file for {task.id}")
                    recreated += 1
                    repaired = True
                else:
                    try:
                        rec_raw = json.loads(rec_path.read_text(encoding="utf-8"))
                        detail = TaskDetailFile.model_validate(rec_raw)
                        if (
                            detail.checksum != self._compute_detail_checksum(detail)
                            or detail.done != task.done
                            or detail.task != task.task
                        ):
                            self._write_detail_file(
                                task,
                                document_chunks=detail.document_chunks,
                                extracted_entities=detail.extracted_entities,
                            )
                            issues.append(f"Synchronized detail record {task.id}.json")
                            repaired = True
                    except (json.JSONDecodeError, ValidationError):
                        self._write_detail_file(task)
                        issues.append(f"Rebuilt corrupted detail record {task.id}.json")
                        repaired = True

            # Remove orphaned record files not present in tasks.json
            for rec_file in self.records_dir.glob("*.json"):
                if rec_file.stem not in valid_ids:
                    rec_file.unlink()
                    orphan_removed += 1
                    repaired = True
                    issues.append(f"Removed orphaned record file {rec_file.name}")

            if repaired:
                store = self._save_store(store)
            else:
                # Touch validation timestamp without altering payload checksum
                store.integrity.valid = True
                store.integrity.last_validated_at = utc_now_iso()
                self._atomic_write_json(self.tasks_file, store.model_dump(mode="json"))

            report = IntegrityReport(
                valid=True,
                repaired=repaired,
                issues=issues,
                checksum=store.integrity.checksum,
                record_count=len(store.tasks),
                orphan_files_removed=orphan_removed,
                missing_records_recreated=recreated,
            )
            return store, report

    def add_task(
        self,
        task_text: str,
        priority: TaskPriority = "med",
        added: Optional[str] = None,
        source: str = "command",
        tags: Optional[list[str]] = None,
        ai_notes: str = "",
        document_source: Optional[str] = None,
        document_chunks: Optional[list[str]] = None,
        extracted_entities: Optional[list[str]] = None,
    ) -> tuple[TaskStore, TaskRecord]:
        with self._lock:
            store = self.load_store()
            task_id = f"tsk_{uuid.uuid4().hex[:8]}"
            created_at = utc_now_iso()
            record = TaskRecord(
                id=task_id,
                index=len(store.tasks) + 1,
                task=task_text.strip(),
                done=False,
                priority=priority,
                added=added or display_time_now(),
                created_at=created_at,
                completed_at=None,
                detail_file=f"data/records/{task_id}.json",
                source=source,
                metadata=TaskMetadata(
                    tags=tags or [],
                    ai_notes=ai_notes,
                    document_source=document_source,
                    chunk_count=len(document_chunks or []),
                ),
            )
            store.tasks.append(record)

            # Update Mon..Sun activity counter for current weekday
            day_idx = datetime.now().weekday()  # Mon=0 .. Sun=6
            store.activity[day_idx] += 1

            self._write_detail_file(
                record,
                document_chunks=document_chunks,
                extracted_entities=extracted_entities,
            )
            store = self._save_store(store)
            return store, store.tasks[-1]

    def complete_task(self, one_based_index: int) -> tuple[TaskStore, TaskRecord, bool]:
        """Returns (store, record, already_done)."""
        with self._lock:
            store = self.load_store()
            idx = one_based_index - 1
            if idx < 0 or idx >= len(store.tasks):
                raise IndexError("Invalid task number")
            target = store.tasks[idx]
            if target.done:
                return store, target, True

            target.done = True
            target.completed_at = utc_now_iso()

            rec_path = self.records_dir / f"{target.id}.json"
            chunks: list[str] = []
            entities: list[str] = []
            if rec_path.exists():
                try:
                    existing = TaskDetailFile.model_validate(
                        json.loads(rec_path.read_text(encoding="utf-8"))
                    )
                    chunks = existing.document_chunks
                    entities = existing.extracted_entities
                except Exception:
                    pass

            self._write_detail_file(
                target,
                document_chunks=chunks,
                extracted_entities=entities,
            )
            store = self._save_store(store)
            return store, store.tasks[idx], False

    def delete_task(self, one_based_index: int) -> tuple[TaskStore, TaskRecord]:
        with self._lock:
            store = self.load_store()
            idx = one_based_index - 1
            if idx < 0 or idx >= len(store.tasks):
                raise IndexError("Invalid task number")

            removed = store.tasks.pop(idx)
            self._delete_detail_file(removed.id)
            store = self._save_store(store)
            return store, removed

    def delete_completed_tasks(self) -> tuple[TaskStore, list[TaskRecord]]:
        with self._lock:
            store = self.load_store()
            removed = [t for t in store.tasks if t.done]
            store.tasks = [t for t in store.tasks if not t.done]
            for task in removed:
                self._delete_detail_file(task.id)
            store = self._save_store(store)
            return store, removed


dbms = LocalJsonTaskDBMS()
