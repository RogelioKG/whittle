"""ComfyUI HTTP API: /prompt to submit, /history to poll, /view to download, /upload/image to upload."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid

POLL_INTERVAL_S = 2
TIMEOUT_S = 30 * 60


class ComfyClient:
    def __init__(self, url: str):
        self.url = url.rstrip("/")

    def _request(
        self, path: str, data: bytes | None = None, headers: dict | None = None
    ) -> bytes:
        req = urllib.request.Request(self.url + path, data=data, headers=headers or {})
        try:
            with urllib.request.urlopen(req) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(
                f"ComfyUI {path} returned {e.code}: {e.read().decode(errors='replace')}"
            ) from e

    def submit(self, workflow: dict) -> str:
        body = json.dumps({"prompt": workflow, "client_id": uuid.uuid4().hex}).encode()
        resp = json.loads(
            self._request("/prompt", body, {"Content-Type": "application/json"})
        )
        return resp["prompt_id"]

    def wait(self, prompt_id: str) -> dict:
        """Wait until the prompt finishes and return its outputs."""
        deadline = time.monotonic() + TIMEOUT_S
        while time.monotonic() < deadline:
            history = json.loads(self._request(f"/history/{prompt_id}"))
            if prompt_id in history:
                entry = history[prompt_id]
                status = entry.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(
                        f"ComfyUI execution failed: {json.dumps(status.get('messages'), ensure_ascii=False)}"
                    )
                return entry["outputs"]
            time.sleep(POLL_INTERVAL_S)
        raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out")

    def download(self, file_info: dict) -> bytes:
        query = urllib.parse.urlencode(
            {k: file_info[k] for k in ("filename", "subfolder", "type")}
        )
        return self._request(f"/view?{query}")

    def upload_image(self, name: str, data: bytes) -> str:
        """Upload an image to ComfyUI's input folder and return the name for Load Image."""
        boundary = uuid.uuid4().hex
        body = (
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="image"; filename="{name}"\r\n'
                "Content-Type: application/octet-stream\r\n\r\n"
            ).encode()
            + data
            + (
                f"\r\n--{boundary}\r\n"
                'Content-Disposition: form-data; name="overwrite"\r\n\r\n'
                f"true\r\n--{boundary}--\r\n"
            ).encode()
        )
        headers = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
        resp = json.loads(self._request("/upload/image", body, headers))
        return (
            f"{resp['subfolder']}/{resp['name']}"
            if resp.get("subfolder")
            else resp["name"]
        )

    def run(self, workflow: dict, out_node: str) -> list[bytes]:
        """Submit, wait, and download every file written by out_node."""
        outputs = self.wait(self.submit(workflow)).get(out_node, {})
        # Save Image reports under "images", Save 3D Model under another key; take any file list
        files = [
            f
            for v in outputs.values()
            if isinstance(v, list)
            for f in v
            if isinstance(f, dict) and "filename" in f
        ]
        if not files:
            raise RuntimeError(f"Output node {out_node} produced no files")
        return [self.download(f) for f in files]
