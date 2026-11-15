# Banner A: the armoured car between the two tanks on the meadow road, golden hour. t=7.0 (car smug).
Y = -60.0
place("Car", (0.0, Y + 0.6, 0)); place("CarSpin", rot=(0, 0, 0))
place("TankA", (-2.0, Y - 2.2, 0), (0, 0, R(-10))); place("TankB", (2.0, Y - 2.2, 0), (0, 0, R(10)))
for f_, ex in ((a_face, 0.3), (b_face, -0.3)):
    for e in f_.eyes: e.animation_data_clear(); e.scale = (1, 1, 0.9)
    for pu in f_.pupils: pu.animation_data_clear(); pu.location = (ex * f_.r, f_.r * 0.42, 0.05 * f_.r)
for d in descendants(bpy.data.objects["Wind"]): d.hide_render = True
cam((1.35, Y + 30, 2.4), (1.35, Y, 0.85), 85, fstop=5.6)
