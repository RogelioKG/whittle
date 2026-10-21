import gradio as gr
from pydantic import ValidationError

from whittle.jobs import Jobs
from whittle.manifest import Projects
from whittle.ui.status import STATUS_LABELS, job_label

HEADERS = ["專案", "id", "狀態", "任務", "subject"]


def build(
    projects: Projects,
    jobs: Jobs,
    tab: gr.Tab,
    demo: gr.Blocks,
    timer: gr.Timer,
    current_tab: gr.State,
) -> None:
    with gr.Accordion("📥 部件匯入", open=True):
        text = gr.Textbox(
            label="manifest JSON",
            placeholder="貼上所有部件的 JSON",
            lines=10,
            max_lines=20,
        )
        submit = gr.Button("📥 匯入", variant="primary")
        message = gr.Markdown()
    with gr.Accordion("📊 部件總覽", open=True):
        table = gr.Dataframe(headers=HEADERS, interactive=False, wrap=True)
        requeue = gr.Button("🔁 重新排入未完成的部件")
    with gr.Accordion("🗑️ 部件刪除", open=False):
        delete_id = gr.Dropdown(label="要刪除的部件")
        delete = gr.Button("🗑️ 刪除", variant="stop")
        with gr.Row(visible=False, equal_height=True) as confirm_row:
            confirm_text = gr.Markdown()
            confirm = gr.Button("確定刪除", variant="stop", scale=0)
            cancel = gr.Button("取消", scale=0)

    def overview() -> dict:
        rows = [
            [
                key.split("/")[0],
                p.id,
                STATUS_LABELS[p.status],
                job_label(jobs, key, p),
                p.subject,
            ]
            for key, p in projects.parts()
        ]
        return {"headers": HEADERS, "data": rows}

    def part_choices() -> gr.Dropdown:
        return gr.Dropdown(choices=[key for key, _ in projects.parts()], value=None)

    def ask_delete(key: str | None) -> tuple | dict:
        if not key:
            gr.Warning("請先選擇部件")
            return gr.skip()
        return (
            gr.Row(visible=True),
            f"⚠️ 確定刪除 **{key}**？圖片、模型與 FBX 會一併刪除，無法復原。",
        )

    def refresh() -> tuple[dict, gr.Dropdown]:
        return overview(), part_choices()

    def do_delete(key: str | None) -> tuple:
        try:
            jobs.remove(key)
        except RuntimeError:
            gr.Warning(f"⚙️ {key} 處理中，完成後再刪除")
            return gr.Row(visible=False), overview(), gr.skip()
        except ValueError:
            gr.Warning(f"找不到部件 {key}")
        else:
            gr.Info(f"🗑️ 已刪除 {key}")
        return gr.Row(visible=False), *refresh()

    def do_import(raw: str) -> tuple:
        try:
            project, added, skipped = projects.import_json(raw)
        except ValidationError as e:
            lines = [
                f"- `{'.'.join(map(str, err['loc'])) or '(root)'}`：{err['msg']}"
                for err in e.errors()
            ]
            message = "❌ **驗證失敗，未寫入：**\n" + "\n".join(lines)
            return raw, message, *refresh()
        for part_id in added:
            jobs.enqueue(f"{project}/{part_id}")
        lines = [f"✅ {project} 新增 {len(added)} 件：{', '.join(added) or '無'}"]
        if skipped:
            lines.append(f"⏭️ 跳過 {len(skipped)} 件 (已存在)：{', '.join(skipped)}")
        if added:
            lines.append("🎨 已排入生圖，完成後到「圖片審核」選圖。")
        return "", "\n\n".join(lines), *refresh()

    def do_requeue() -> dict:
        jobs.enqueue_unfinished()
        gr.Info("🔁 已重新排入未完成的部件")
        return overview()

    def tick(tab_name: str) -> dict:
        return overview() if tab_name == "import" else gr.skip()

    submit.click(do_import, text, [text, message, table, delete_id])
    requeue.click(do_requeue, None, table)
    delete.click(ask_delete, delete_id, [confirm_row, confirm_text])
    confirm.click(do_delete, delete_id, [confirm_row, table, delete_id])
    cancel.click(lambda: gr.Row(visible=False), None, confirm_row)
    # Confirm always refers to the id currently shown, so changing it cancels
    delete_id.change(lambda: gr.Row(visible=False), None, confirm_row)
    timer.tick(tick, current_tab, table, show_progress="hidden")
    tab.select(refresh, None, [table, delete_id])
    demo.load(refresh, None, [table, delete_id])
