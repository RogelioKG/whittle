import tomllib
from pathlib import Path

from pydantic import BaseModel, Field

PACKAGE = Path(__file__).resolve().parent
DEFAULT_CONFIG = Path.home() / "whittle" / "config.toml"


class ComfyConfig(BaseModel):
    url: str = "http://127.0.0.1:8188"
    t2i_workflow: Path = PACKAGE / "comfy" / "t2i.api.json"
    i2m_workflow: Path = PACKAGE / "comfy" / "i2m.api.json"


class BlenderConfig(BaseModel):
    exe: str = "blender"
    script: Path = PACKAGE / "blender" / "process_mesh.py"


class ReviewConfig(BaseModel):
    candidates: int = 4


class Config(BaseModel):
    projects: Path = Path("projects")  # one subdirectory per project
    comfyui: ComfyConfig = Field(default_factory=ComfyConfig)
    blender: BlenderConfig = Field(default_factory=BlenderConfig)
    review: ReviewConfig = Field(default_factory=ReviewConfig)


def load_config(path: Path | None = None) -> Config:
    """Load the given config.toml, or ~/whittle/config.toml (defaults if missing)."""
    required = path is not None
    path = (path or DEFAULT_CONFIG).expanduser().resolve()
    if path.exists():
        config = Config.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    elif required:
        raise FileNotFoundError(f"Config file not found: {path}")
    else:
        config = Config()
    # Relative paths are relative to the config file's directory
    base = path.parent
    config.projects = base / config.projects.expanduser()
    config.comfyui.t2i_workflow = base / config.comfyui.t2i_workflow.expanduser()
    config.comfyui.i2m_workflow = base / config.comfyui.i2m_workflow.expanduser()
    config.blender.script = base / config.blender.script.expanduser()
    return config
