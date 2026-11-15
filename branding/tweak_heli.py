# Banner B: the helicopter hovering over its hills. t=0.5
place("Heli", (-1.25, 8.5, 6.0), (0, 0, R(-18)))
for n in ("Spaa", "TankA", "TankB", "VicA", "VicB"):
    if n in bpy.data.objects:
        for d in descendants(bpy.data.objects[n]): d.hide_render = True
cam((0.0, 38.5, 3.2), (0.0, 8.5, 6.1), 105, fstop=8.0)
