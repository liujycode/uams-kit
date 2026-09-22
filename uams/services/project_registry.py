"""Persistent project registration and exact path/alias resolution."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

from uams.models.project_record import ProjectRecord
from uams.utils.interprocess_lock import InterProcessFileLock
from uams.utils.path_normalization import normalize_path


REGISTRY_SCHEMA_VERSION = 2


class ProjectRegistryError(RuntimeError):
    """Base registry error."""


class ProjectNotFound(ProjectRegistryError):
    """Raised when no registered project matches the supplied paths."""

    def __init__(self, paths: Iterable[str]):
        self.paths = tuple(paths)
        super().__init__(f"no registered project matches: {', '.join(self.paths)}")


class ProjectConflict(ProjectRegistryError):
    """Raised when more than one project claims a path or identity."""

    def __init__(self, project_ids: Iterable[str], paths: Iterable[str] = ()):
        self.project_ids = tuple(project_ids)
        self.paths = tuple(paths)
        super().__init__(f"conflicting registered projects: {', '.join(self.project_ids)}")


ProjectResolutionError = ProjectRegistryError
ProjectResolutionNotFound = ProjectNotFound
ProjectResolutionConflict = ProjectConflict


class ProjectRegistry:
    """Manage the authoritative one-project-per-normalized-path mapping."""

    def __init__(self, uams_root: str | os.PathLike[str]):
        self._uams_root = Path(uams_root).resolve()
        self._path = self._uams_root / "registry" / "projects.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = InterProcessFileLock(self._path.parent / ".projects.lock")

    @property
    def uams_root(self) -> Path:
        return self._uams_root

    @property
    def path(self) -> Path:
        return self._path

    @property
    def registry_path(self) -> Path:
        return self._path

    def register(
        self,
        project_path: str,
        workspace_aliases: Optional[Iterable[str]] = None,
        project_id: Optional[str] = None,
        **kwargs,
    ) -> ProjectRecord:
        """Register a project only if its ID, path and aliases are unclaimed."""
        project_id = project_id or kwargs.pop("projectId", None)
        if workspace_aliases is None:
            workspace_aliases = kwargs.pop("workspacePaths", kwargs.pop("normalizedWorkspaceAliases", None))
        normalized_project = normalize_path(project_path)
        aliases = sorted({normalize_path(alias) for alias in (workspace_aliases or [])} - {normalized_project})
        record = ProjectRecord(
            projectId=project_id or ProjectRecord().projectId,
            normalizedProjectPath=normalized_project,
            normalizedWorkspaceAliases=aliases,
            memoryLocation="",
        )
        record.memoryLocation = str(self._uams_root / "memory" / "projects" / record.projectId)
        with self._write_lock:
            records = self.list_projects()
            self._assert_available(record, records)
            records.append(record)
            self._save(records)
        return record

    register_project = register

    def add_workspace_aliases(self, project_id: str, workspace_aliases: Iterable[str]) -> ProjectRecord:
        """Add aliases atomically and reject aliases claimed by any other project."""
        with self._write_lock:
            records = self.list_projects()
            target = next((record for record in records if record.projectId == project_id), None)
            if target is None:
                raise ProjectNotFound((project_id,))
            additions = {normalize_path(alias) for alias in workspace_aliases} - {target.normalizedProjectPath}
            candidate = ProjectRecord(
                projectId=target.projectId,
                normalizedProjectPath=target.normalizedProjectPath,
                normalizedWorkspaceAliases=sorted({*target.normalizedWorkspaceAliases, *additions}),
                memoryLocation=target.memoryLocation,
                createdAt=target.createdAt,
                updatedAt=datetime.now(timezone.utc),
            )
            self._assert_available(candidate, [record for record in records if record.projectId != project_id])
            self._save([candidate if record.projectId == project_id else record for record in records])
        return candidate

    add_workspace_alias = add_workspace_aliases

    def list_projects(self) -> list[ProjectRecord]:
        if not self._path.is_file():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                version = data.get("schemaVersion", 1)
                if version not in {1, REGISTRY_SCHEMA_VERSION}:
                    raise ValueError("unsupported schema version")
                rows = data.get("projects", [])
            else:
                rows = data
            if not isinstance(rows, list):
                raise TypeError("projects must be an array")
            return [ProjectRecord.from_dict(row) for row in rows]
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise ProjectRegistryError(f"invalid project registry: {self._path}") from exc

    projects = list_projects

    def get(self, project_id: str) -> ProjectRecord:
        for record in self.list_projects():
            if record.projectId == project_id:
                return record
        raise ProjectNotFound((project_id,))

    get_project = get

    def resolve(
        self,
        project_path: Optional[str] = None,
        workspace_path: Optional[str] = None,
        **kwargs,
    ) -> ProjectRecord:
        """Resolve exactly one project by exact normalized root or alias."""
        project_path = project_path or kwargs.pop("projectPath", None)
        workspace_path = workspace_path or kwargs.pop("workspacePath", None)
        supplied = [path for path in (project_path, workspace_path) if path]
        normalized = [normalize_path(path) for path in supplied]
        if not normalized:
            raise ProjectNotFound(())
        matches: list[ProjectRecord] = []
        for record in self.list_projects():
            candidate_paths = {record.normalizedProjectPath, *record.normalizedWorkspaceAliases}
            if any(path in candidate_paths for path in normalized):
                matches.append(record)
        unique: dict[str, ProjectRecord] = {record.projectId: record for record in matches}
        if not unique:
            raise ProjectNotFound(normalized)
        if len(unique) > 1:
            raise ProjectConflict(unique.keys(), normalized)
        return next(iter(unique.values()))

    resolve_project = resolve
    resolve_project_id = lambda self, *args, **kwargs: self.resolve(*args, **kwargs).projectId

    def resolve_id(self, project_path: Optional[str] = None, workspace_path: Optional[str] = None, **kwargs) -> str:
        return self.resolve(project_path, workspace_path, **kwargs).projectId

    @staticmethod
    def _paths(record: ProjectRecord) -> set[str]:
        return {record.normalizedProjectPath, *record.normalizedWorkspaceAliases}

    def _assert_available(self, candidate: ProjectRecord, existing_records: list[ProjectRecord]) -> None:
        candidate_paths = self._paths(candidate)
        for existing in existing_records:
            if existing.projectId == candidate.projectId:
                raise ProjectConflict((candidate.projectId,), candidate_paths)
            overlap = candidate_paths & self._paths(existing)
            if overlap:
                raise ProjectConflict((candidate.projectId, existing.projectId), sorted(overlap))

    def _save(self, records: list[ProjectRecord]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_name = tempfile.mkstemp(prefix=".projects-", suffix=".tmp", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as output:
                json.dump(
                    {"schemaVersion": REGISTRY_SCHEMA_VERSION, "projects": [record.to_dict() for record in records]},
                    output,
                    indent=2,
                    ensure_ascii=False,
                )
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary_name, self._path)
        except Exception:
            try:
                os.unlink(temporary_name)
            except OSError:
                pass
            raise
