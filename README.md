# whittle

Generate images with ComfyUI, turn them into 3D models, decimate them into low-poly game props with Blender, and review both in a Gradio UI.

## Setup

1. Install uv, Blender, and ComfyUI on the same host.
2. Install whittle: `uv tool install git+https://github.com/RogelioKG/whittle`
3. (Optional) Create `~/whittle/config.toml` to set the ComfyUI URL, Blender path, and number of candidate images per part.
4. Start ComfyUI, then run `whittle` (see `whittle --help`).
5. Open `http://127.0.0.1:7860`:
    - Local: open it directly.
    - Remote:
        - SSH: on the client, run `ssh -L 7860:localhost:7860 <host>`, then open the URL above.
        - Tailscale: on the host, run `tailscale serve 7860`. On the client (same tailnet), open `https://<host>.<tailnet>.ts.net`.
        - Cloudflare: on the host, run `cloudflared tunnel --url http://localhost:7860`. On the client, open the printed URL. Anyone with it can get in, so add Cloudflare Access.
6. (Optional) Install the page as an app from the browser's address bar.

## How to use

1. Break down: give `docs/PROMPT.md` and a scene description to an agent to get the JSON.
2. Import: paste the JSON; parts are grouped by `project`.
3. Image review: pick an image, or edit the subject and rerun.
4. Model review:
    - Good: approve and export FBX.
    - Size or face count off: adjust parameters and update the preview.
    - Wrong shape: rerun the model.
5. Output: `~/whittle/projects/<project>/parts/<id>/<id>.fbx` (next to the config file if `--config` is given).

## Development

1. `git clone https://github.com/RogelioKG/whittle`
2. `uv sync`
3. `uv run whittle --config config.toml` (uses the repo's `config.toml` and `projects/`)
4. Before committing: `uv run ruff check` and `uv run ruff format`
5. Architecture: `docs/ARCHITECTURE.md`
