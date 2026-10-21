"""Breakpoint 1: pick one of the candidate images, or rerun."""

import gradio as gr

from whittle.jobs import Jobs
from whittle.manifest import Part, Projects

EMPTY = (
    "### 目前沒有待審核的圖片\n"
    "生圖完成後會自動出現在這裡，進度見上方狀態列。"
)

def build(
    projects: Projects,
    jobs: Jobs,
    tab: gr.Tab,
    demo: gr.Blocks,
    timer: gr.Timer,
    current_tab: gr.State,
) -> None:
    part_key = gr.State(None)  # "<project>/<id>"
    seed = gr.State(None)
    info = gr.Markdown(EMPTY)
    # Same section style as the overview tab: accordion, content, full-width button
    with gr.Column(visible=False) as body:
        with gr.Accordion("🖼️ 圖片選定", open=True):
            gallery = gr.Gallery(
                label="候選圖 (點選一張)",
                # Gallery takes a fixed column count and never wraps; 2 fits a phone
                columns=2,
                object_fit="contain",
                height="auto",
            )
            approve = gr.Button("✅ 選定這張", variant="primary")
        with gr.Accordion("🔄 圖片重跑", open=True):
            subject = gr.Textbox(label="✏️ 修改 subject")
            rerun = gr.Button("🔄 全部重跑")
    outputs = [part_key, seed, info, body, gallery, subject]

    def render(parts: list[tuple[str, Part]]) -> tuple:
        if not parts:
            return None, None, EMPTY, gr.Column(visible=False), [], ""
        key, part = parts[0]
        images = [(str(path), f"seed {path.stem}") for path in jobs.candidates(key)]
        return (
            key,
            None,
            (
                f"### 🖼️ {key}　·　剩餘 {len(parts)} 件待選圖\n"
                "點選最滿意的一張後按「選定」；都不滿意就修改 subject 後重跑。"
            ),
            gr.Column(visible=True),
            # Clear the previous part's selection so it matches the reset seed
            gr.Gallery(images, selected_index=None),
            part.subject,
        )

    def show() -> tuple:
        return render(jobs.ready_parts("pending_image"))

    def tick(key: str | None, tab_name: str) -> tuple | dict:
        # Only fill an empty, visible page, so a part under review is never swapped out
        if key is None and tab_name == "image":
            parts = jobs.ready_parts("pending_image")
            if parts:
                return render(parts)
        return gr.skip()

    def on_select(key: str | None, evt: gr.SelectData) -> int | None:
        return int(jobs.candidates(key)[evt.index].stem) if key else None

    # gr.Error would mark every output as errored, so input problems use a warning
    # toast and leave the page unchanged with gr.skip()
    def do_approve(key: str | None, s: int | None) -> tuple | dict:
        if key is None:
            gr.Warning("目前沒有部件")
            return gr.skip()
        if s is None:
            gr.Warning("請先點選一張圖")
            return gr.skip()
        manifest, part_id = projects.locate(key)
        path = next(p for p in jobs.candidates(key) if p.stem == str(s))
        manifest.approve_image(part_id, s, path.relative_to(manifest.dir).as_posix())
        jobs.enqueue(key)
        gr.Info(f"✅ 已選定 {key}，開始生模型")
        return show()

    def do_rerun(key: str | None, new_subject: str) -> tuple | dict:
        if key is None:
            gr.Warning("目前沒有部件")
            return gr.skip()
        if not new_subject.strip():
            gr.Warning("subject 不可空白")
            return gr.skip()
        jobs.rerun_images(key, new_subject.strip())
        gr.Info(f"🔄 {key} 重新生圖中，完成後會再出現")
        return show()

    gallery.select(on_select, part_key, seed)
    approve.click(do_approve, [part_key, seed], outputs)
    rerun.click(do_rerun, [part_key, subject], outputs)
    timer.tick(tick, [part_key, current_tab], outputs, show_progress="hidden")
    tab.select(show, None, outputs)
    demo.load(show, None, outputs)
