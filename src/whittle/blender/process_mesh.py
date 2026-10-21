"""Run inside Blender (bpy and stdlib only).

blender --background --python process_mesh.py -- --mode <create|update|export> --part-dir <path> --params <json>

create: import GLB -> uniform scale by ref_axis -> Remesh + Decimate (not applied) -> save .blend, write previews
update: update the .blend with new params, rewrite previews
export: export FBX with modifiers applied

On success, create/update write preview/result.json and export writes export.json.
On failure, the traceback goes to stderr and the exit code is 1.
"""

import argparse
import json
import math
import sys
import traceback
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

PREVIEW_RES = 768
MIN_ISLAND_RATIO = 0.01


def parse_args() -> tuple[str, Path, dict]:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["create", "update", "export"], required=True)
    parser.add_argument("--part-dir", type=Path, required=True)
    parser.add_argument("--params", default="{}")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1 :])
    return args.mode, args.part_dir.resolve(), json.loads(args.params)


def select_only(obj: bpy.types.Object) -> None:
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def face_count(obj: bpy.types.Object) -> int:
    bpy.context.view_layer.update()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    return len(obj.evaluated_get(depsgraph).data.polygons)


def remove_debris(obj: bpy.types.Object) -> int:
    """Delete tiny floating islands; they would inflate the measured size. Returns how many."""
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    seen: set[bmesh.types.BMVert] = set()
    small: list[bmesh.types.BMVert] = []
    removed = 0
    for start in bm.verts:
        if start in seen:
            continue
        seen.add(start)
        island, stack = [], [start]
        while stack:
            v = stack.pop()
            island.append(v)
            for e in v.link_edges:
                other = e.other_vert(v)
                if other not in seen:
                    seen.add(other)
                    stack.append(other)
        if len(island) < MIN_ISLAND_RATIO * len(bm.verts):
            small += island
            removed += 1
    bmesh.ops.delete(bm, geom=small, context="VERTS")
    bm.to_mesh(obj.data)
    bm.free()
    return removed


def import_glb(path: Path, name: str) -> bpy.types.Object:
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o)
    bpy.ops.import_scene.gltf(filepath=str(path))
    meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    if not meshes:
        raise RuntimeError(f"No mesh in {path}")

    # A GLB may hold several meshes under empties: join into one object with transforms applied
    for o in bpy.context.view_layer.objects:
        o.select_set(o in meshes)
    bpy.context.view_layer.objects.active = meshes[0]
    bpy.ops.object.parent_clear(type="CLEAR_KEEP_TRANSFORM")
    if len(meshes) > 1:
        bpy.ops.object.join()
    obj = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for o in list(bpy.data.objects):
        if o != obj:
            bpy.data.objects.remove(o)
    obj.name = obj.data.name = name
    obj["whittle_islands_removed"] = remove_debris(obj)

    # Put the bottom center at the origin. Measure from vertices: obj.bound_box is
    # stale until the depsgraph updates, so it would still include the debris
    coords = [v.co for v in obj.data.vertices]
    lo = Vector(min(c[i] for c in coords) for i in range(3))
    hi = Vector(max(c[i] for c in coords) for i in range(3))
    obj.data.transform(
        Matrix.Translation(-Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z)))
    )
    obj["whittle_raw_dims"] = list(hi - lo)
    obj["whittle_scale"] = 1.0

    remesh = obj.modifiers.new("Remesh", "REMESH")
    remesh.mode = "VOXEL"
    decimate = obj.modifiers.new("Decimate", "DECIMATE")
    decimate.decimate_type = "COLLAPSE"
    return obj


def apply_params(obj: bpy.types.Object, params: dict) -> dict:
    raw = Vector(list(obj["whittle_raw_dims"]))
    ref = raw.z if params["ref_axis"] == "height" else max(raw)
    scale = params["ref_size_m"] / ref
    # Scale is baked into the mesh so voxel_size is in meters
    obj.data.transform(Matrix.Scale(scale / obj["whittle_scale"], 4))
    obj.data.update()
    obj["whittle_scale"] = scale

    obj.modifiers["Remesh"].voxel_size = params["voxel_size"]
    decimate = obj.modifiers["Decimate"]
    decimate.ratio = 1.0
    faces_remesh = face_count(obj)
    target = params["target_faces"]
    decimate.ratio = min(1.0, target / faces_remesh)
    # Collapse works on triangles, so correct once using the measured count
    faces_final = face_count(obj)
    if faces_final:
        decimate.ratio = min(1.0, decimate.ratio * target / faces_final)

    return {
        "params": params,
        "scale": scale,
        "dimensions_m": list(obj.dimensions),
        "faces_original": len(obj.data.polygons),
        "islands_removed": obj["whittle_islands_removed"],
        "faces_remesh": faces_remesh,
        "faces_final": face_count(obj),
    }


def setup_render(obj: bpy.types.Object) -> None:
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = scene.render.resolution_y = PREVIEW_RES
    scene.render.image_settings.file_format = "PNG"
    scene.view_settings.view_transform = "Standard"
    scene.world = scene.world or bpy.data.worlds.new("World")
    scene.world.color = (1.0, 1.0, 1.0)
    scene.display.shading.light = "STUDIO"

    # Three-quarter front view (front is -Y after glTF import)
    corners = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    center = sum(corners, Vector()) / 8
    radius = max((c - center).length for c in corners)
    cam_data = bpy.data.cameras.new("preview_cam")
    distance = radius / math.sin(cam_data.angle / 2) * 1.05
    cam_data.clip_end = distance * 10
    cam = bpy.data.objects.new("preview_cam", cam_data)
    scene.collection.objects.link(cam)
    direction = Vector((1.0, -1.4, 0.8)).normalized()
    cam.location = center + direction * distance
    cam.rotation_euler = (-direction).to_track_quat("-Z", "Y").to_euler()
    scene.camera = cam


def render(path: Path) -> None:
    bpy.context.scene.render.filepath = str(path)
    bpy.ops.render.render(write_still=True)


def write_previews(obj: bpy.types.Object, preview_dir: Path) -> None:
    """Call after saving the .blend: this adds a camera, materials and a modifier that are not saved."""
    preview_dir.mkdir(exist_ok=True)
    select_only(obj)
    bpy.ops.export_scene.gltf(
        filepath=str(preview_dir / "decimated.glb"),
        export_format="GLB",
        use_selection=True,
        export_apply=True,
    )

    setup_render(obj)
    shading = bpy.context.scene.display.shading

    shading.color_type = "SINGLE"
    shading.single_color = (0.75, 0.75, 0.75)
    for m in obj.modifiers:
        m.show_render = False
    render(preview_dir / "original.png")

    for m in obj.modifiers:
        m.show_render = True
    body = bpy.data.materials.new("preview_body")
    body.diffuse_color = (0.8, 0.8, 0.8, 1.0)
    wire_mat = bpy.data.materials.new("preview_wire")
    wire_mat.diffuse_color = (0.05, 0.05, 0.05, 1.0)
    obj.data.materials.clear()
    obj.data.materials.append(body)
    obj.data.materials.append(wire_mat)
    wire = obj.modifiers.new("preview_wire", "WIREFRAME")
    wire.thickness = max(obj.dimensions) * 0.004
    wire.use_replace = False
    wire.material_offset = 1
    shading.color_type = "MATERIAL"
    render(preview_dir / "wireframe.png")


def main() -> None:
    mode, part_dir, params = parse_args()
    part_id = part_dir.name
    blend = part_dir / f"{part_id}.blend"
    preview_dir = part_dir / "preview"
    bpy.context.preferences.filepaths.save_version = 0  # no .blend1 backups

    # On failure, print the traceback and exit 1 without touching the result file,
    # so a failed update keeps the previous preview
    try:
        if mode == "create":
            obj = import_glb(Path(params["glb"]), part_id)
            result = apply_params(obj, params)
        elif mode == "update":
            bpy.ops.wm.open_mainfile(filepath=str(blend))
            obj = bpy.data.objects[part_id]
            result = apply_params(obj, params)
        else:
            bpy.ops.wm.open_mainfile(filepath=str(blend))
            obj = bpy.data.objects[part_id]
            fbx = part_dir / f"{part_id}.fbx"
            select_only(obj)
            bpy.ops.export_scene.fbx(
                filepath=str(fbx),
                use_selection=True,
                use_mesh_modifiers=True,
                object_types={"MESH"},
            )
            result = {"fbx": str(fbx), "faces_final": face_count(obj)}

        if mode in ("create", "update"):
            bpy.ops.wm.save_as_mainfile(filepath=str(blend))
            write_previews(obj, preview_dir)
    except Exception:  # noqa: BLE001
        print(traceback.format_exc(), file=sys.stderr)
        sys.exit(1)

    result_path = (
        part_dir / "export.json" if mode == "export" else preview_dir / "result.json"
    )
    result_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8"
    )


main()
