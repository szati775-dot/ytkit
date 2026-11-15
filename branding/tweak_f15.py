for n in ("EX", "EXBody"):
    o = bpy.data.objects[n]; o.animation_data_clear(); o.rotation_euler = (0, 0, 0); o.delta_rotation_euler = (0, 0, 0)
    print("ROT", n, o.rotation_mode, o.parent, [c.type for c in o.constraints])
bpy.data.objects["EXBody"].rotation_euler = (0, R(-10), 0)
