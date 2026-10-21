import argparse
from pathlib import Path

from whittle import ui
from whittle.config import DEFAULT_CONFIG, load_config
from whittle.jobs import Jobs
from whittle.manifest import Projects


def main() -> None:
    parser = argparse.ArgumentParser(prog="whittle")
    parser.add_argument(
        "--config",
        type=Path,
        help="path to config.toml (default: ~/whittle/config.toml, built-in defaults if absent)",
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=7860)
    args = parser.parse_args()

    config = load_config(args.config)
    config_path = (args.config or DEFAULT_CONFIG).expanduser().resolve()
    found = "" if config_path.exists() else " (not found, using defaults)"
    print(f"Config:   {config_path}{found}")
    print(f"Projects: {config.projects}")
    projects = Projects(config.projects)
    jobs = Jobs(config, projects)
    jobs.enqueue_unfinished()
    ui.build(config, projects, jobs).launch(
        server_name=args.host,
        server_port=args.port,
        allowed_paths=[str(projects.root)],
        pwa=True,
        favicon_path=Path(__file__).parent / "resources" / "favicon.svg",
    )


if __name__ == "__main__":
    main()
