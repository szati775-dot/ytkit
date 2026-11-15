"""Channel branding stills from the Blender Shorts scenes.
python3 brand_render.py SRC.py --t 7.0 --res 2560x1440 --o out.png [--tweak tweak.py] [--samples 64] [--transparent]
Runs the episode script up to its RENDER section (builds the scene + animation), jumps to time t,
then runs the tweak file (which may define/select a camera as scene.camera) and renders one still."""
import sys, os
me = sys.argv[1:]
src = me[0]
def opt(n, d=None):
    return me[me.index(n) + 1] if n in me else d
code = open(src).read().split("# ================================================================ RENDER")[0]
sys.argv = ["blender", "--", "--out", "/tmp"]
g = {"__name__": "__main__"}
exec(compile(code, src, "exec"), g)
import bpy
scene = g["scene"]; F = g["F"]
t = float(opt("--t", "0"))
f = F(t); scene.frame_set(f)
for mk in sorted(scene.timeline_markers, key=lambda m: m.frame):
    if mk.frame <= f: scene.camera = mk.camera
r = scene.render
r.engine = "CYCLES"
w, h = opt("--res", "2560x1440").split("x")
r.resolution_x, r.resolution_y = int(w), int(h); r.resolution_percentage = int(opt("--scale", "100"))
r.use_motion_blur = False
cy = scene.cycles; cy.samples = int(opt("--samples", "64")); cy.use_adaptive_sampling = True; cy.use_denoising = True; cy.max_bounces = 4
vs = scene.view_settings
try: vs.view_transform = "Standard"; vs.look = "Medium High Contrast"
except Exception as ex: print(ex)
r.film_transparent = "--transparent" in me
from mathutils import Vector
def descendants(o):
    out = [o]
    for c in o.children: out += descendants(c)
    return out
def only(*names):
    keep = set()
    for n in names: keep |= set(descendants(bpy.data.objects[n]))
    for o in bpy.data.objects:
        if o.type in ("MESH", "FONT", "CURVE") and o not in keep: o.hide_render = True
def hide_caps():
    for o in bpy.data.objects:
        if o.name.startswith("Cap_"):
            for d in descendants(o): d.hide_render = True
def place(o, loc=None, rot=None, scale=None):
    if isinstance(o, str): o = bpy.data.objects[o]
    o.animation_data_clear()
    if loc is not None: o.location = loc
    if rot is not None: o.rotation_euler = rot
    if scale is not None: o.scale = scale
def cam(loc, target, lens=50, fstop=None):
    cd = bpy.data.cameras.new("BrandCam"); cd.lens = lens; cd.clip_end = 3000
    c = bpy.data.objects.new("BrandCam", cd); scene.collection.objects.link(c); c.location = loc
    t = bpy.data.objects.new("BrandAim", None); scene.collection.objects.link(t); t.location = target
    con = c.constraints.new("TRACK_TO"); con.target = t; con.track_axis = "TRACK_NEGATIVE_Z"; con.up_axis = "UP_Y"
    if fstop: cd.dof.use_dof = True; cd.dof.focus_object = t; cd.dof.aperture_fstop = fstop
    scene.camera = c; return c
g.update(only=only, hide_caps=hide_caps, place=place, cam=cam, Vector=Vector, descendants=descendants)
hide_caps()
for mk in list(scene.timeline_markers): scene.timeline_markers.remove(mk)
if opt("--only"):
    root = bpy.data.objects[opt("--only")]; only(opt("--only"))
    bpy.context.view_layer.update()
    base = root.matrix_world.translation.copy()
    co = Vector([float(v) for v in opt("--camoff").split(",")]); ao = Vector([float(v) for v in opt("--aimoff", "0,0,0").split(",")])
    cam(base + co, base + ao, float(opt("--lens", "50")))
if opt("--tweak"):
    g.update(scene=scene, bpy=bpy)
    exec(compile(open(opt("--tweak")).read(), opt("--tweak"), "exec"), g)
    bpy.context.view_layer.update()
r.image_settings.file_format = "PNG"
r.filepath = os.path.abspath(opt("--o"))
bpy.ops.render.render(write_still=True)
print("DONE")
