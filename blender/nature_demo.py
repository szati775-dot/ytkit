"""Test scene for nature.py: blender -b -P nature_demo.py -- out.png [scale%] [samples]"""
import math
import os
import sys

import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import nature  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
out = argv[0] if argv else "nature_demo.png"
scale = int(argv[1]) if len(argv) > 1 else 50
samples = int(argv[2]) if len(argv) > 2 else 32

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
g = nature.ground(size=40, res=120, height=0.8, seed=4)
tufts = [nature.grass_tuft(seed=i, dry=0.15 * (i % 3)) for i in range(6)]
nature.scatter(g, tufts, density=60, seed=1, scale=(0.7, 1.4), patchiness=0.4)
rocks = [nature.boulder(seed=i) for i in range(4)]
nature.scatter(g, rocks, density=0.06, seed=7, scale=(0.3, 1.1), name="Rocks", patchiness=0)
big = nature.boulder(seed=11, size=1.6)
sc.collection.objects.link(big)
big.location = (0.8, -1.0, nature.ground_height(g, 0.8, -1.0) - 0.15)

cam_data = bpy.data.cameras.new("Cam")
cam_data.lens = 28
cam = bpy.data.objects.new("Cam", cam_data)
sc.collection.objects.link(cam)
cam.location = (0, -6, nature.ground_height(g, 0, -6) + 1.7)
cam.rotation_euler = (math.radians(76), 0, 0)
sc.camera = cam

sun = bpy.data.objects.new("Sun", bpy.data.lights.new("Sun", "SUN"))
sun.data.energy = 4
sun.data.angle = math.radians(3)
sun.rotation_euler = (math.radians(60), math.radians(10), math.radians(-35))
sc.collection.objects.link(sun)
w = bpy.data.worlds.new("Sky")
if hasattr(w, "use_nodes") and bpy.app.version < (5, 0, 0):
    w.use_nodes = True
bg = w.node_tree.nodes["Background"]
bg.inputs["Color"].default_value = (0.3, 0.5, 0.9, 1)
bg.inputs["Strength"].default_value = 0.9
sc.world = w

sc.render.engine = "CYCLES"
sc.cycles.device = "CPU"
sc.cycles.samples = samples
sc.cycles.use_denoising = True
sc.render.resolution_x, sc.render.resolution_y = 1080, 1920
sc.render.resolution_percentage = scale
sc.render.filepath = os.path.abspath(out)
sc.view_settings.view_transform = "Standard"   # the series look (v0.02+)
for look in ("Medium High Contrast", "Standard - Medium High Contrast"):
    try:
        sc.view_settings.look = look
        break
    except TypeError:
        pass
bpy.ops.render.render(write_still=True)
print("DONE", out)
