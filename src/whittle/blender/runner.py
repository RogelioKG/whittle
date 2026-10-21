"""Run process_mesh.py in headless Blender."""

import json
import subprocess
from pathlib import Path
from typing import Literal

from whittle.config import BlenderConfig


def run(
    config: BlenderConfig,
    mode: Literal["create", "update", "export"],
    part_dir: Path,
    params: dict,
) -> dict:
    cmd = [
        config.exe,
        "--background",
        "--factory-startup",
        "--python-exit-code",
        "1",
        "--python",
        str(config.script),
        "--",
        "--mode",
        mode,
        "--part-dir",
        str(part_dir),
        "--params",
        json.dumps(params),
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"Blender {mode} failed (exit {proc.returncode}):\n{proc.stderr[-3000:]}"
        )
    result_path = (
        part_dir / "export.json"
        if mode == "export"
        else part_dir / "preview" / "result.json"
    )
    return json.loads(result_path.read_text(encoding="utf-8"))


def read_preview(part_dir: Path) -> dict | None:
    """Return preview/result.json, or None if the preview is not ready."""
    path = part_dir / "preview" / "result.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
