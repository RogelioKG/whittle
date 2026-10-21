import gradio as gr

from whittle.config import Config
from whittle.jobs import Jobs
from whittle.manifest import Projects
from whittle.ui import import_page, review_image, review_model, status

REFRESH_S = 1
STAT_SLOTS = 5  # the most counts status.banner returns


def build(config: Config, projects: Projects, jobs: Jobs) -> gr.Blocks:
    with gr.Blocks(title="whittle") as demo:
        gr.Markdown("# 🪵 whittle")
        # A Row wraps its children on a narrow screen, so each count stays whole
        with gr.Group():
            now = gr.Markdown(padding=True)
            with gr.Row():
                slots = [
                    gr.Textbox(interactive=False, min_width=100)
                    for _ in range(STAT_SLOTS)
                ]
        timer = gr.Timer(REFRESH_S)
        current_tab = gr.State("import")
        with gr.Tab("📥 匯入總覽") as import_tab:
            import_page.build(projects, jobs, import_tab, demo, timer, current_tab)
        with gr.Tab("🖼️ 圖片審核") as image_tab:
            review_image.build(projects, jobs, image_tab, demo, timer, current_tab)
        with gr.Tab("🧊 模型審核") as model_tab:
            review_model.build(config, projects, jobs, model_tab, timer, current_tab)

        for name, tab in [
            ("import", import_tab),
            ("image", image_tab),
            ("model", model_tab),
        ]:
            tab.select(lambda name=name: name, None, current_tab)

        def update_banner() -> list:
            text, stats = status.banner(projects, jobs)
            # Fill the slots in order and hide the unused ones
            return [text] + [
                gr.Textbox(stats[i][1], label=stats[i][0], visible=True)
                if i < len(stats)
                else gr.Textbox(visible=False)
                for i in range(STAT_SLOTS)
            ]

        banner = [now, *slots]
        timer.tick(update_banner, None, banner, show_progress="hidden")
        demo.load(update_banner, None, banner)
    return demo
