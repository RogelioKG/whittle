"""Status labels and the activity banner shared by every tab."""

import time

from whittle.jobs import Activity, Jobs
from whittle.manifest import Part, Projects

STATUS_LABELS = {
    "pending_image": "🖼️ 待生圖",
    "image_approved": "🧊 待建模",
    "done": "✅ 已完成",
}
STEP_LABELS = {
    "image": "🖼️ 生圖中",
    "model": "🧊 建模中",
    "blender": "🔧 減面中",
}


def elapsed(started: float) -> str:
    s = int(time.monotonic() - started)
    return f"{s // 60} 分 {s % 60:02d} 秒" if s >= 60 else f"{s} 秒"


def detail(a: Activity) -> str:
    """Progress and elapsed time, e.g. "(2/4，37 秒)"."""
    if not a.total:
        return f"({elapsed(a.started)})"
    return f"({a.index}/{a.total}，{elapsed(a.started)})"


def job_label(jobs: Jobs, key: str, part: Part) -> str:
    if key in jobs.errors:
        return f"❌ 失敗：{jobs.errors[key]}"
    a = jobs.activity
    if a and a.key == key:
        return f"{STEP_LABELS[a.step]} {detail(a)}"
    if key in jobs.queued:
        return "⏳ 排隊中"
    if part.status == "done":
        return ""
    return "👀 待審核" if jobs.ready(key, part) else "⏸️ 未排隊"


def banner(projects: Projects, jobs: Jobs) -> tuple[str, list[tuple[str, str]]]:
    """The worker's current step, and the counts as (label, value) in display order."""
    keyed = projects.parts()
    if not keyed:
        return "📭 尚未匯入任何部件，請到「匯入總覽」貼上 manifest JSON。", []
    parts = [p for _, p in keyed]
    a = jobs.activity
    if a:
        now = f"{STEP_LABELS[a.step]} **{a.key}** {detail(a)}"
    elif jobs.queued:
        now = "⚙️ 準備中"
    else:
        now = "💤 閒置中"
    ready = [p for key, p in keyed if jobs.ready(key, p)]
    pick = sum(p.status == "pending_image" for p in ready)
    done = sum(p.status == "done" for p in parts)
    # Every label reads "<emoji> <3-char label>"; failures only show when present
    stats = [
        # queued includes the part the worker holds
        ("⏳ 排隊中", f"{max(len(jobs.queued) - (jobs.running is not None), 0)} 件"),
        ("🖼️ 待選圖", f"{pick} 件"),
        ("🧊 待驗收", f"{len(ready) - pick} 件"),
    ]
    if jobs.errors:
        stats.append(("❌ 已失敗", f"{len(jobs.errors)} 件"))
    stats.append(
        (f"{'🎉' if done == len(parts) else '✅'} 已完成", f"{done}/{len(parts)} 件")
    )
    return now, stats
