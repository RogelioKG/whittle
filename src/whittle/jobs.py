"""Background queue. A job does whatever the part's manifest status calls for and skips outputs that already exist.

In-progress work is never written to the manifest; on restart every unfinished part is queued again.
Parts from every project share one queue and are addressed by key "<project>/<id>".
"""

import os
import queue
import random
import shutil
import threading
import time
import traceback
from pathlib import Path
from typing import Literal, NamedTuple

from whittle import blender
from whittle.comfy import ComfyClient, workflows
from whittle.config import Config
from whittle.manifest import Part, Projects, Status


class Activity(NamedTuple):
    """What the worker is doing right now, for the UI."""

    key: str
    step: Literal["image", "model", "blender"]
    started: float  # time.monotonic()
    index: int = 0  # image index / total for the "image" step, 0 otherwise
    total: int = 0


def write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class Jobs:
    def __init__(self, config: Config, projects: Projects):
        self.config = config
        self.projects = projects
        self.comfy = ComfyClient(config.comfyui.url)
        self.t2i = workflows.load(config.comfyui.t2i_workflow, workflows.T2I_TITLES)
        self.i2m = workflows.load(config.comfyui.i2m_workflow, workflows.I2M_TITLES)
        self._queue: queue.Queue[str] = queue.Queue()
        self._lock = threading.Lock()
        self.queued: set[str] = set()  # waiting or running
        self.errors: dict[str, str] = {}
        self.running: str | None = None  # part the worker holds; it cannot be removed
        self.activity: Activity | None = None
        threading.Thread(target=self._loop, daemon=True).start()

    def enqueue(self, key: str) -> None:
        with self._lock:
            if key in self.queued:
                return
            self.queued.add(key)
            self.errors.pop(key, None)
        self._queue.put(key)

    def enqueue_unfinished(self) -> None:
        for key, part in self.projects.parts():
            if part.status != "done" and not self.ready(key, part):
                self.enqueue(key)

    def candidates(self, key: str) -> list[Path]:
        return sorted((self.projects.part_dir(key) / "images").glob("*.png"))

    def ready(self, key: str, part: Part) -> bool:
        """Whether the part's outputs are on disk and waiting at a breakpoint."""
        if part.status == "pending_image":
            return len(self.candidates(key)) >= self.config.review.candidates
        if part.status == "image_approved":
            return blender.read_preview(self.projects.part_dir(key)) is not None
        return False

    def ready_parts(self, status: Status) -> list[tuple[str, Part]]:
        """(key, part) waiting at the breakpoint for status, earliest finished first."""
        parts = [
            (key, p)
            for key, p in self.projects.parts()
            if p.status == status and self.ready(key, p)
        ]
        return sorted(parts, key=lambda kp: self._ready_at(*kp))

    def _ready_at(self, key: str, part: Part) -> float:
        """When the part reached its breakpoint: mtime of its last candidate or its preview."""
        if part.status == "pending_image":
            return max(p.stat().st_mtime for p in self.candidates(key))
        return (self.projects.part_dir(key) / "preview" / "result.json").stat().st_mtime

    def rerun_images(self, key: str, subject: str) -> None:
        manifest, part_id = self.projects.locate(key)
        manifest.set_subject(part_id, subject)
        shutil.rmtree(self.projects.part_dir(key) / "images", ignore_errors=True)
        self.enqueue(key)

    def rerun_model(self, key: str) -> None:
        part_dir = self.projects.part_dir(key)
        shutil.rmtree(part_dir / "model", ignore_errors=True)
        shutil.rmtree(part_dir / "preview", ignore_errors=True)
        for name in (f"{part_dir.name}.blend", f"{part_dir.name}.fbx", "export.json"):
            (part_dir / name).unlink(missing_ok=True)
        self.enqueue(key)

    def remove(self, key: str) -> None:
        """Delete the part from its manifest and its directory.

        Raises RuntimeError while the worker is processing it, ValueError if it does not exist.
        """
        with self._lock:
            if self.running == key:
                raise RuntimeError(f"{key} is being processed")
            manifest, part_id = self.projects.locate(key)
            manifest.remove(part_id)
            # A copy may still sit in the queue; the worker skips it once it is gone
            self.queued.discard(key)
            self.errors.pop(key, None)
            shutil.rmtree(manifest.part_dir(part_id), ignore_errors=True)

    def _loop(self) -> None:
        while True:
            key = self._queue.get()
            # Claim the part before reading it, so remove() either refuses or wins outright
            with self._lock:
                self.running = key
            try:
                part = self.projects.get(key)
                if part is None:  # removed while queued; finally still runs
                    continue
                if part.status == "pending_image":
                    self._images(key, part)
                elif part.status == "image_approved":
                    self._model(key, part)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.errors[key] = str(e)
            finally:
                self.activity = None
                with self._lock:
                    self.running = None
                    self.queued.discard(key)

    def _images(self, key: str, part: Part) -> None:
        out_node = workflows.find_node(self.t2i, "OUT_image")
        images_dir = self.projects.part_dir(key) / "images"
        total = self.config.review.candidates
        while (done := len(self.candidates(key))) < total:
            self.activity = Activity(key, "image", time.monotonic(), done + 1, total)
            seed = random.randrange(2**32)
            data = self.comfy.run(
                workflows.t2i(self.t2i, part.subject, seed), out_node
            )[0]
            write_atomic(images_dir / f"{seed}.png", data)

    def _model(self, key: str, part: Part) -> None:
        manifest, _ = self.projects.locate(key)
        part_dir = self.projects.part_dir(key)
        glbs = sorted((part_dir / "model").glob("*.glb"))
        if not glbs:
            self.activity = Activity(key, "model", time.monotonic())
            image = manifest.dir / part.image.path
            # Same id in two projects must not overwrite each other's upload
            name = self.comfy.upload_image(
                f"whittle_{key.replace('/', '_')}{image.suffix}", image.read_bytes()
            )
            seed = random.randrange(2**32)
            out_node = workflows.find_node(self.i2m, "OUT_mesh")
            data = self.comfy.run(workflows.i2m(self.i2m, name, seed), out_node)[0]
            glbs = [part_dir / "model" / f"{seed}.glb"]
            write_atomic(glbs[0], data)
        if blender.read_preview(part_dir) is None:
            self.activity = Activity(key, "blender", time.monotonic())
            params = {
                "glb": str(glbs[0]),
                "ref_axis": part.ref_axis,
                "ref_size_m": part.ref_size_m,
                **part.decimate.model_dump(),
            }
            blender.run(self.config.blender, "create", part_dir, params)
