"""Breakpoint 2: review the decimated model, adjust parameters, approve, or rerun the model."""

import gradio as gr

from whittle import blender
from whittle.config import Config
from whittle.jobs import Jobs
from whittle.manifest import Decimate, Outputs, Part, Projects, SeedPath

EMPTY = (
    "### 目前沒有待審核的模型\n"
    "生模型與減面完成後會自動出現在這裡，進度見上方狀態列。"
)


def build(
    config: Config,
    projects: Projects,
    jobs: Jobs,
    tab: gr.Tab,
    timer: gr.Timer,
    current_tab: gr.State,
) -> None:
    part_key = gr.State(None)  # "<project>/<id>"
    info = gr.Markdown(EMPTY)
    # Same section style as the overview tab: accordion, content, full-width button.
    # The preview is never hidden by code: Model3D breaks if it gets a value while hidden
    with gr.Accordion("🧊 模型預覽", open=True) as preview_section:
        with gr.Row():
            model = gr.Model3D(label="減面模型", height=480)
            wireframe = gr.Image(label="減面線框", height=480)
        with gr.Row():
            original = gr.Image(label="原始模型", height=360)
            image = gr.Image(label="選定圖片", height=360)
    with gr.Column(visible=False) as controls:
        with gr.Accordion("🔧 參數調整", open=True):
            with gr.Row():
                ref_axis = gr.Radio(["height", "longest"], label="基準軸")
                ref_size = gr.Number(label="基準尺寸 (m)")
                voxel_size = gr.Number(label="voxel size (m)")
                target_faces = gr.Number(label="目標面數", precision=0)
            update = gr.Button("🔧 更新預覽")
        with gr.Accordion("✅ 模型驗收", open=True), gr.Row():
            approve = gr.Button("✅ 通過，匯出 FBX", variant="primary")
            rerun = gr.Button("🔄 造型不對，重跑模型")
    outputs = [
        part_key,
        info,
        controls,
        model,
        wireframe,
        original,
        image,
        ref_axis,
        ref_size,
        voxel_size,
        target_faces,
    ]

    def current_model(key: str | None) -> str | None:
        return (
            str(projects.part_dir(key) / "preview" / "decimated.glb") if key else None
        )

    def render(key: str | None, part: Part | None, remaining: int) -> tuple:
        if key is None or part is None:
            return None, EMPTY, gr.Column(visible=False), *[None] * 8
        manifest, _ = projects.locate(key)
        part_dir = projects.part_dir(key)
        preview = part_dir / "preview"
        r = blender.read_preview(part_dir)
        p = r["params"]
        x, y, z = r["dimensions_m"]
        text = (
            f"### 🧊 {key}　·　剩餘 {remaining} 件待審核\n"
            f"> {part.subject}\n\n"
            f"🔺 面數 {r['faces_original']:,} → Remesh {r['faces_remesh']:,} → **{r['faces_final']:,}**　"
            f"📏 尺寸 {x:.2f} × {y:.2f} × {z:.2f} m　🔍 縮放 ×{r['scale']:.3f}"
        )
        return (
            key,
            text,
            gr.Column(visible=True),
            current_model(key),
            str(preview / "wireframe.png"),
            str(preview / "original.png"),
            str(manifest.dir / part.image.path),
            p["ref_axis"],
            p["ref_size_m"],
            p["voxel_size"],
            p["target_faces"],
        )

    def show() -> tuple:
        parts = jobs.ready_parts("image_approved")
        return render(*(parts[0] if parts else (None, None)), len(parts))

    def tick(key: str | None, tab_name: str) -> tuple | dict:
        # Only fill an empty page, and only while its tab is visible (see below)
        if key is None and tab_name == "model":
            parts = jobs.ready_parts("image_approved")
            if parts:
                return render(*parts[0], len(parts))
        return gr.skip()

    def run_blender(mode: str, key: str, params: dict) -> dict | None:
        try:
            return blender.run(config.blender, mode, projects.part_dir(key), params)
        except RuntimeError as e:
            print(e)
            gr.Warning(str(e)[-800:], duration=None)
            return None

    # gr.Error would mark every output as errored, so input problems use a warning
    # toast and leave the page unchanged with gr.skip()
    def do_update(
        key: str | None,
        axis: str,
        size: float,
        voxel: float,
        target: float,
        progress=gr.Progress(),  # noqa: B008 (Gradio's documented idiom)
    ) -> tuple | dict:
        if key is None:
            gr.Warning("目前沒有部件")
            return gr.skip()
        if not (size and size > 0 and voxel and voxel > 0 and target and target > 0):
            gr.Warning("基準尺寸、voxel size、目標面數都必須大於 0")
            return gr.skip()
        params = {
            "ref_axis": axis,
            "ref_size_m": size,
            "voxel_size": voxel,
            "target_faces": int(target),
        }
        progress(None, desc="🔧 Blender 更新預覽中…")
        if run_blender("update", key, params) is None:
            return gr.skip()
        gr.Info("🔧 預覽已更新")
        remaining = len(jobs.ready_parts("image_approved"))
        return render(key, projects.get(key), remaining)

    def do_approve(key: str | None, progress=gr.Progress()) -> tuple | dict:  # noqa: B008
        if key is None:
            gr.Warning("目前沒有部件")
            return gr.skip()
        manifest, part_id = projects.locate(key)
        part_dir = manifest.part_dir(part_id)
        # Record the parameters actually in the .blend, not unapplied edits in the form
        p = blender.read_preview(part_dir)["params"]
        progress(None, desc="📦 Blender 匯出 FBX 中…")
        if run_blender("export", key, {}) is None:
            return gr.skip()
        glb = min((part_dir / "model").glob("*.glb"))

        def rel(path) -> str:
            return path.relative_to(manifest.dir).as_posix()

        manifest.finish(
            part_id,
            ref_axis=p["ref_axis"],
            ref_size_m=p["ref_size_m"],
            decimate=Decimate(
                voxel_size=p["voxel_size"], target_faces=p["target_faces"]
            ),
            model=SeedPath(seed=int(glb.stem), path=rel(glb)),
            outputs=Outputs(
                blend=rel(part_dir / f"{part_id}.blend"),
                fbx=rel(part_dir / f"{part_id}.fbx"),
            ),
        )
        gr.Info(f"📦 {key} 完成，已匯出 {part_dir / f'{part_id}.fbx'}")
        return show()

    def do_rerun(key: str | None) -> tuple | dict:
        if key is None:
            gr.Warning("目前沒有部件")
            return gr.skip()
        jobs.rerun_model(key)
        gr.Info(f"🔄 {key} 重新生模型中，完成後會再出現")
        return show()

    approve.click(do_approve, part_key, outputs)
    update.click(
        do_update, [part_key, ref_axis, ref_size, voxel_size, target_faces], outputs
    )
    rerun.click(do_rerun, part_key, outputs)
    # No demo.load here: Gradio 6.30's Model3D never creates its canvas if it gets a
    # value while its tab is hidden, so fill it only once the tab is visible
    timer.tick(tick, [part_key, current_tab], outputs, show_progress="hidden")
    tab.select(show, None, outputs)
    # If the model changed while the preview was collapsed, its canvas is blank;
    # resending the same value does nothing, but clearing first rebuilds it
    preview_section.expand(lambda: None, None, model, show_progress="hidden").then(
        current_model, part_key, model, show_progress="hidden"
    )
