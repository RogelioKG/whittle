"""Inject parameters into API-format workflows by interface node title."""

import copy
import json
from pathlib import Path

T2I_TITLES = ("IN_subject", "IN_seed", "OUT_image")
I2M_TITLES = ("IN_image", "IN_seed", "OUT_mesh")


def find_node(workflow: dict, title: str) -> str:
    ids = [k for k, n in workflow.items() if n.get("_meta", {}).get("title") == title]
    if len(ids) != 1:
        raise ValueError(
            f"Workflow needs exactly one node titled {title}, found {len(ids)}"
        )
    return ids[0]


def load(path: Path, titles: tuple[str, ...]) -> dict:
    workflow = json.loads(path.read_text(encoding="utf-8"))
    for title in titles:
        find_node(workflow, title)
    return workflow


def _set(workflow: dict, title: str, key: str, value: object) -> None:
    workflow[find_node(workflow, title)]["inputs"][key] = value


def t2i(workflow: dict, subject: str, seed: int) -> dict:
    workflow = copy.deepcopy(workflow)
    _set(workflow, "IN_subject", "value", subject)
    _set(workflow, "IN_seed", "value", seed)
    return workflow


def i2m(workflow: dict, image_name: str, seed: int) -> dict:
    workflow = copy.deepcopy(workflow)
    _set(workflow, "IN_image", "image", image_name)
    _set(workflow, "IN_seed", "value", seed)
    return workflow
