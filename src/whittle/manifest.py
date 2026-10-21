"""The only writer of manifest.json."""

import os
import shutil
import threading
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Status = Literal["pending_image", "image_approved", "done"]
RefAxis = Literal["height", "longest"]


class Decimate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    voxel_size: float = Field(gt=0)
    target_faces: int = Field(gt=0)


class PartSpec(BaseModel):
    """Fields provided by the agent."""

    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    subject: str = Field(min_length=1)
    ref_axis: RefAxis
    ref_size_m: float = Field(gt=0)
    decimate: Decimate


class SeedPath(BaseModel):
    seed: int | None = None
    path: str | None = None


class Outputs(BaseModel):
    blend: str | None = None
    fbx: str | None = None


class Part(PartSpec):
    """Fields maintained by the review script are added on top of PartSpec."""

    status: Status = "pending_image"
    image: SeedPath = Field(default_factory=SeedPath)
    model: SeedPath = Field(default_factory=SeedPath)
    outputs: Outputs = Field(default_factory=Outputs)


class ManifestData(BaseModel):
    project: str
    parts: list[Part]


class ImportSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    project: str = Field(pattern=r"^[A-Za-z0-9_-]+$")  # also the directory name
    parts: list[PartSpec] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> "ImportSpec":
        ids = [p.id for p in self.parts]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        if dupes:
            raise ValueError(f"Duplicate id: {', '.join(dupes)}")
        return self


class Manifest:
    def __init__(self, project_dir: Path):
        self.dir = project_dir
        self.path = project_dir / "manifest.json"
        self._lock = threading.Lock()

    def load(self) -> ManifestData:
        if not self.path.exists():
            return ManifestData(project=self.dir.name, parts=[])
        return ManifestData.model_validate_json(self.path.read_text(encoding="utf-8"))

    def part_dir(self, part_id: str) -> Path:
        return self.dir / "parts" / part_id

    def get(self, part_id: str) -> Part | None:
        return next((p for p in self.load().parts if p.id == part_id), None)

    def _save(self, data: ManifestData) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def merge(self, spec: ImportSpec) -> tuple[list[str], list[str]]:
        """Merge by id. Returns (added, skipped)."""
        with self._lock:
            data = self.load()
            existing = {p.id for p in data.parts}
            added = [p.id for p in spec.parts if p.id not in existing]
            skipped = [p.id for p in spec.parts if p.id in existing]
            if not added:
                return added, skipped
            if self.path.exists():
                backups = self.dir / "backups"
                backups.mkdir(exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
                shutil.copy2(self.path, backups / f"manifest-{stamp}.json")
            data.parts += [Part(**p.model_dump()) for p in spec.parts if p.id in added]
            self._save(data)
            return added, skipped

    def remove(self, part_id: str) -> None:
        """Drop the part. Raises ValueError if it does not exist."""
        with self._lock:
            data = self.load()
            parts = [p for p in data.parts if p.id != part_id]
            if len(parts) == len(data.parts):
                raise ValueError(f"No part with id {part_id}")
            data.parts = parts
            self._save(data)

    def _update(
        self, part_id: str, expected: Status, fn: Callable[[Part], None]
    ) -> None:
        with self._lock:
            data = self.load()
            part = next(p for p in data.parts if p.id == part_id)
            if part.status != expected:
                raise ValueError(
                    f"{part_id} has status {part.status}, expected {expected}"
                )
            fn(part)
            self._save(data)

    def set_subject(self, part_id: str, subject: str) -> None:
        def fn(p: Part) -> None:
            p.subject = subject

        self._update(part_id, "pending_image", fn)

    def approve_image(self, part_id: str, seed: int, path: str) -> None:
        def fn(p: Part) -> None:
            p.status = "image_approved"
            p.image = SeedPath(seed=seed, path=path)

        self._update(part_id, "pending_image", fn)

    def finish(
        self,
        part_id: str,
        ref_axis: RefAxis,
        ref_size_m: float,
        decimate: Decimate,
        model: SeedPath,
        outputs: Outputs,
    ) -> None:
        def fn(p: Part) -> None:
            p.status = "done"
            p.ref_axis = ref_axis
            p.ref_size_m = ref_size_m
            p.decimate = decimate
            p.model = model
            p.outputs = outputs

        self._update(part_id, "image_approved", fn)


class Projects:
    """Every project under one root directory, each with its own manifest.json.

    Across projects a part is addressed by its key "<project>/<id>".
    """

    def __init__(self, root: Path):
        self.root = root
        self._manifests: dict[str, Manifest] = {}
        self._lock = threading.Lock()

    def manifest(self, project: str) -> Manifest:
        # One Manifest per project, so each project keeps a single write lock
        with self._lock:
            if project not in self._manifests:
                self._manifests[project] = Manifest(self.root / project)
            return self._manifests[project]

    def locate(self, key: str) -> tuple[Manifest, str]:
        project, part_id = key.split("/", 1)
        return self.manifest(project), part_id

    def parts(self) -> list[tuple[str, Part]]:
        """(key, part) for every part, by project name, then manifest order."""
        return [
            (f"{path.parent.name}/{p.id}", p)
            for path in sorted(self.root.glob("*/manifest.json"))
            for p in self.manifest(path.parent.name).load().parts
        ]

    def get(self, key: str) -> Part | None:
        manifest, part_id = self.locate(key)
        return manifest.get(part_id)

    def part_dir(self, key: str) -> Path:
        manifest, part_id = self.locate(key)
        return manifest.part_dir(part_id)

    def import_json(self, text: str) -> tuple[str, list[str], list[str]]:
        """Merge into the project the JSON names, creating it if needed.

        Returns (project, added ids, skipped ids). Raises ValidationError on bad input.
        """
        spec = ImportSpec.model_validate_json(text)
        added, skipped = self.manifest(spec.project).merge(spec)
        return spec.project, added, skipped
