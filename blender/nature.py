"""nature.py - procedural ground, grass tufts and boulders for the Blender Shorts.

Ported from Infinigen (Princeton University, BSD-3-Clause, see
THIRD_PARTY.md and blender/LICENSE-infinigen.txt):
  grass_tuft()  infinigen/assets/objects/grassland/grass_tuft.py (blade curl maths)
  boulder()     infinigen/assets/objects/rocks/boulder.py (convex hull, top-face
                extrusion, two Voronoi displacements)
  grass palette infinigen/assets/materials/plant/grass_blade.py (dry/green ramps)
Rewritten to plain bpy + bmesh (no Infinigen install, no gin/trimesh) and to
build meshes with from_pydata instead of bpy.ops, so it runs fast in
background renders. Works in Blender 4.2+ and 5.x.

Use from an episode script:
    import sys; sys.path.insert(0, r"C:/Users/sz_at/Documents/Grinder Shorts/lib")
    import nature
    ground = nature.ground(size=60, seed=3)
    tufts = [nature.grass_tuft(seed=i) for i in range(4)]
    nature.scatter(ground, tufts, density=40, seed=1)
    rocks = [nature.boulder(seed=i) for i in range(3)]
    nature.scatter(ground, rocks, density=0.05, seed=2, scale=(0.4, 1.4), name="Rocks")
"""
import math
import random

import bmesh
import bpy
import numpy as np
from mathutils import Vector, noise

# --------------------------------------------------------------- palettes
# A few stops from Infinigen's grass_blade palettes (green summer, dry autumn)
GREEN = [(0.13, 0.18, 0.034), (0.22, 0.28, 0.079), (0.31, 0.36, 0.12), (0.45, 0.43, 0.19)]
DRY = [(0.26, 0.15, 0.056), (0.41, 0.24, 0.11), (0.59, 0.44, 0.27), (0.83, 0.75, 0.45)]


def _collection(name):
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        bpy.context.scene.collection.children.link(col)
    return col


def _hidden_collection():
    col = _collection("_nature_sources")
    col.hide_render = True
    col.hide_viewport = True
    return col


def _obj(name, mesh, col=None):
    ob = bpy.data.objects.new(name, mesh)
    (col or bpy.context.scene.collection).objects.link(ob)
    return ob


# ----------------------------------------------------------------- ground
def ground(size=60.0, res=160, height=1.2, scale=0.06, seed=0, name="Ground", material=None):
    """Rolling ground: a grid displaced by fBm noise (heights in metres)."""
    off = Vector((seed * 17.3, seed * 5.1, 0))
    xs = np.linspace(-size / 2, size / 2, res + 1)
    verts, faces = [], []
    for j, y in enumerate(xs):
        for i, x in enumerate(xs):
            p = Vector((x * scale, y * scale, 0)) + off
            z = noise.fractal(p, 0.6, 2.0, 4) * height
            verts.append((x, y, z))
    w = res + 1
    for j in range(res):
        for i in range(res):
            a = j * w + i
            faces.append((a, a + 1, a + w + 1, a + w))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.shade_smooth() if hasattr(me, "shade_smooth") else None
    ob = _obj(name, me)
    ob.data.materials.append(material or ground_material())
    return ob


def ground_height(ground_ob, x, y):
    """Height of the ground under (x, y), for placing vehicles on it."""
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get()
    tree = BVHTree.FromObject(ground_ob, dg)
    hit = tree.ray_cast(Vector((x, y, 1000)), Vector((0, 0, -1)))
    return hit[0].z if hit[0] else 0.0


# ------------------------------------------------------------- grass tuft
def grass_tuft(seed=0, n_blades=None, length=None, dry=0.0, name=None):
    """One clump of curled grass blades (Infinigen GrassTuftFactory maths).
    Returns a hidden source object, meant for scatter()."""
    rng = np.random.default_rng(seed)
    n_seg = 4
    length_mean = length or rng.uniform(0.12, 0.26)       # Infinigen: 0.05-0.15 (we film tanks)
    length_std = length_mean * rng.uniform(0.2, 0.5)
    curl_mean = rng.uniform(10, 70)
    curl_std = curl_mean * np.clip(rng.normal(0.3, 0.1), 0.01, 0.6)
    curl_power = rng.normal(1.2, 0.3)
    width_pct = rng.uniform(0.02, 0.045)
    base_spread = rng.uniform(0, length_mean / 4)
    base_angle_var = rng.uniform(0, 15)
    n = n_blades or int(rng.integers(30, 60))

    lens = np.abs(rng.normal(length_mean, length_std, (n, 1))) + 0.02
    seg = lens / n_seg
    curls = rng.normal(curl_mean, curl_std, (n, n_seg))
    curls *= np.power(np.linspace(0, 1, n_seg).reshape(1, n_seg), curl_power)
    ang = np.cumsum(np.deg2rad(curls), axis=-1)
    ang -= ang[:, [0]]
    rad = np.arange(n_seg).reshape(1, n_seg) * seg
    px = np.cumsum(rad * np.cos(ang), axis=-1)            # along the blade
    pz = np.cumsum(rad * np.sin(ang), axis=-1)            # curl
    widths = lens.reshape(-1) * np.abs(rng.normal(width_pct, 0.01, n))
    taper = np.linspace(1, 0.05, n_seg)

    base_a = rng.uniform(0, 2 * np.pi, n)
    base_r = rng.uniform(0, base_spread, n)
    facing = np.deg2rad(rng.normal(0, base_angle_var, n))
    verts, faces, uvy = [], [], []
    for b in range(n):
        # blade stands up: local x -> world up, curl bends it sideways
        lean = rng.uniform(0, 0.35)
        yaw = -base_a[b] + facing[b]
        c, s = math.cos(yaw), math.sin(yaw)
        ox, oy = -base_r[b] * math.cos(base_a[b]), base_r[b] * math.sin(base_a[b])
        start = len(verts)
        for k in range(n_seg):
            up = px[b, k]
            side = pz[b, k] + lean * up
            hw = widths[b] * taper[k] / 2
            for sgn in (-1, 1):
                lx, ly = side, sgn * hw
                verts.append((ox + lx * c - ly * s, oy + lx * s + ly * c, up - 0.05 * length_mean))
                uvy.append(k / (n_seg - 1))
        for k in range(n_seg - 1):
            a = start + 2 * k
            faces.append((a, a + 1, a + 3, a + 2))
    me = bpy.data.meshes.new(name or "GrassTuft_%d" % seed)
    me.from_pydata(verts, [], faces)
    # 'tip' attribute 0 at the root -> 1 at the tip, used by the material
    attr = me.attributes.new("tip", "FLOAT", "POINT")
    attr.data.foreach_set("value", uvy)
    me.materials.append(grass_material(dry))
    return _obj(me.name, me, _hidden_collection())


# ---------------------------------------------------------------- boulder
def boulder(seed=0, slab=None, size=1.0, name=None, material=None):
    """Chunky rock (Infinigen BoulderFactory recipe, bmesh version)."""
    rng = np.random.default_rng(seed)
    is_slab = (rng.random() < 0.2) if slab is None else slab
    bm = bmesh.new()
    for p in rng.uniform(-1, 1, (32, 3)):
        bm.verts.new(p)
    bmesh.ops.convex_hull(bm, input=bm.verts)
    # Infinigen: extrude some large, upward-facing faces twice, then shrink them
    for prob, extrude, sc in ((rng.uniform(0.2, 0.3), 0.8, 0.4), (0.6, 0.2, 0.6)):
        bm.faces.ensure_lookup_table()
        mean_area = sum(f.calc_area() for f in bm.faces) / len(bm.faces)
        sel = [f for f in bm.faces if f.normal.z > math.cos(math.pi * 2 / 3) and f.normal.z > 0.2
               and f.calc_area() > mean_area and rng.random() < prob]
        for f in sel:
            r = bmesh.ops.extrude_discrete_faces(bm, faces=[f])
            nf = r["faces"][0]
            d = nf.normal * rng.uniform(extrude * 0.5, extrude) * 0.35
            cen = nf.calc_center_median()
            k = rng.uniform(sc * 0.5, sc) + 0.4
            for v in nf.verts:
                v.co = cen + (v.co - cen) * k + d
    sxy = rng.uniform(0.5, 2.0, 2) if is_slab else rng.uniform(0.4, 1.2, 2)
    sz = rng.uniform(0.1, 0.15) if is_slab else rng.uniform(0.4, 0.8)
    rz = rng.uniform(0, 2 * math.pi)
    for v in bm.verts:
        x, y, z = v.co.x * sxy[0], v.co.y * sxy[1], (v.co.z + 0.4) * sz
        v.co = Vector((x * math.cos(rz) - y * math.sin(rz), x * math.sin(rz) + y * math.cos(rz), z)) * size
    me = bpy.data.meshes.new(name or "Boulder_%d" % seed)
    bm.to_mesh(me)
    bm.free()
    ob = _obj(me.name, me, _hidden_collection())
    m = ob.modifiers.new("subdiv", "SUBSURF")
    m.subdivision_type = "SIMPLE"
    m.levels = m.render_levels = 3
    for i, (ns, st) in enumerate(((rng.uniform(0.2, 0.5), 0.12), (rng.uniform(0.05, 0.1), 0.04))):
        tex = bpy.data.textures.new("%s_vor%d" % (me.name, i), type="VORONOI")
        tex.noise_scale = ns * size
        tex.distance_metric = "DISTANCE"
        d = ob.modifiers.new("vor%d" % i, "DISPLACE")
        d.texture = tex
        d.strength = st * size
        d.mid_level = 0
    sm = ob.modifiers.new("smooth", "SUBSURF")
    sm.levels = sm.render_levels = 2
    me.materials.append(material or rock_material(seed))
    return ob


# ---------------------------------------------------------------- scatter
def _sock(sockets, name):
    """First enabled socket called name (Blender 4.x has hidden per-type
    duplicates, 5.x has one socket per name)."""
    for sk in sockets:
        if sk.name == name and getattr(sk, "enabled", True):
            return sk
    return sockets[name]


def _rand(N, kind, seed, lo=None, hi=None):
    r = N.new("FunctionNodeRandomValue")
    r.data_type = kind
    _sock(r.inputs, "Seed").default_value = seed
    if lo is not None:
        _sock(r.inputs, "Min").default_value = lo
        _sock(r.inputs, "Max").default_value = hi
    return r


def scatter(target, sources, density=30.0, seed=0, scale=(0.7, 1.3), name="Grass",
            patchiness=0.5, patch_scale=0.15, align=False):
    """Scatter source objects over target with Geometry Nodes (instances, so
    100k grass tufts stay light). density = instances per square metre;
    patchiness 0..1 leaves bare patches using a noise mask."""
    col = bpy.data.collections.new(name + "_src")
    _hidden_collection().children.link(col)
    for s in sources:
        col.objects.link(s)
    ng = bpy.data.node_groups.new(name + "_scatter", "GeometryNodeTree")
    iface = ng.interface
    iface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    iface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
    N, L = ng.nodes, ng.links
    gi, go = N.new("NodeGroupInput"), N.new("NodeGroupOutput")
    dist = N.new("GeometryNodeDistributePointsOnFaces")
    dist.distribute_method = "RANDOM"
    dist.inputs["Density"].default_value = density
    dist.inputs["Seed"].default_value = seed
    # bare patches: noise -> map range -> selection density factor
    tex = N.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = patch_scale * 10
    ramp = N.new("ShaderNodeMapRange")
    ramp.inputs["From Min"].default_value = 0.35 + 0.2 * patchiness
    ramp.inputs["From Max"].default_value = 0.55 + 0.1 * patchiness
    L.new(tex.outputs["Fac"], ramp.inputs["Value"])
    if patchiness > 0:
        keep = _rand(N, "BOOLEAN", seed + 4)        # soft-edged patches
        L.new(ramp.outputs["Result"], _sock(keep.inputs, "Probability"))
        L.new(_sock(keep.outputs, "Value"), dist.inputs["Selection"])
    ci = N.new("GeometryNodeCollectionInfo")
    ci.inputs["Collection"].default_value = col
    ci.inputs["Separate Children"].default_value = True
    ci.inputs["Reset Children"].default_value = True
    inst = N.new("GeometryNodeInstanceOnPoints")
    inst.inputs["Pick Instance"].default_value = True
    rid = _rand(N, "INT", seed + 1, 0, max(0, len(sources) - 1))
    rot = _rand(N, "FLOAT_VECTOR", seed + 2, (-0.12, -0.12, 0), (0.12, 0.12, 6.283))
    scl = _rand(N, "FLOAT", seed + 3, scale[0], scale[1])
    join = N.new("GeometryNodeJoinGeometry")
    L.new(gi.outputs[0], dist.inputs["Mesh"])
    L.new(dist.outputs["Points"], inst.inputs["Points"])
    L.new(ci.outputs[0], inst.inputs["Instance"])
    L.new(_sock(rid.outputs, "Value"), inst.inputs["Instance Index"])
    L.new(_sock(rot.outputs, "Value"), inst.inputs["Rotation"])
    L.new(_sock(scl.outputs, "Value"), inst.inputs["Scale"])
    L.new(gi.outputs[0], join.inputs[0])
    L.new(inst.outputs[0], join.inputs[0])
    L.new(join.outputs[0], go.inputs[0])
    mod = target.modifiers.new(name, "NODES")
    mod.node_group = ng
    return mod


# -------------------------------------------------------------- materials
def _ramp(nt, stops):
    r = nt.nodes.new("ShaderNodeValToRGB")
    els = r.color_ramp.elements
    els[0].position, els[0].color = 0.0, (*stops[0], 1)
    els[1].position, els[1].color = 1.0, (*stops[-1], 1)
    for i, c in enumerate(stops[1:-1], 1):
        e = els.new(i / (len(stops) - 1))
        e.color = (*c, 1)
    return r


def grass_material(dry=0.0):
    key = "Nature_Grass_%.2f" % dry
    if key in bpy.data.materials:
        return bpy.data.materials[key]
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    # per-instance colour variation (Infinigen picks palette colours by random)
    oinfo = nt.nodes.new("ShaderNodeObjectInfo")
    stops = [tuple(g * (1 - dry) + d * dry for g, d in zip(gc, dc)) for gc, dc in zip(GREEN, DRY)]
    ramp = _ramp(nt, stops)
    nt.links.new(oinfo.outputs["Random"], ramp.inputs["Fac"])
    tip = nt.nodes.new("ShaderNodeAttribute")
    tip.attribute_name = "tip"
    mix = nt.nodes.new("ShaderNodeMix")
    mix.data_type = "RGBA"
    mix.blend_type = "MULTIPLY"
    base_dark = nt.nodes.new("ShaderNodeMapRange")
    base_dark.inputs["To Min"].default_value = 0.35
    nt.links.new(tip.outputs["Fac"], base_dark.inputs["Value"])
    nt.links.new(base_dark.outputs["Result"], mix.inputs["Factor"])
    mix.inputs[6].default_value = (0.2, 0.2, 0.2, 1)
    nt.links.new(ramp.outputs["Color"], mix.inputs[7])
    nt.links.new(ramp.outputs["Color"], mix.inputs[6])
    bright = nt.nodes.new("ShaderNodeMix")
    bright.data_type = "RGBA"
    nt.links.new(base_dark.outputs["Result"], bright.inputs["Factor"])
    bright.inputs[6].default_value = (0.03, 0.04, 0.01, 1)
    nt.links.new(ramp.outputs["Color"], bright.inputs[7])
    nt.links.new(bright.outputs[2], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.55
    for name, val in (("Subsurface Weight", 0.15), ("Transmission Weight", 0.1)):
        if name in bsdf.inputs:
            bsdf.inputs[name].default_value = val
    return m


def rock_material(seed=0):
    key = "Nature_Rock"
    if key in bpy.data.materials:
        return bpy.data.materials[key]
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = 3.0
    tex.inputs["Detail"].default_value = 8.0
    ramp = _ramp(nt, [(0.035, 0.033, 0.03), (0.08, 0.075, 0.068), (0.16, 0.15, 0.135)])
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bump = nt.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.4
    nt.links.new(tex.outputs["Fac"], bump.inputs["Height"])
    nt.links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])
    bsdf.inputs["Roughness"].default_value = 0.85
    return m


def ground_material():
    key = "Nature_Ground"
    if key in bpy.data.materials:
        return bpy.data.materials[key]
    m = bpy.data.materials.new(key)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = nt.nodes["Principled BSDF"]
    tex = nt.nodes.new("ShaderNodeTexNoise")
    tex.inputs["Scale"].default_value = 0.8
    tex.inputs["Detail"].default_value = 6.0
    ramp = _ramp(nt, [(0.09, 0.07, 0.04), (0.13, 0.14, 0.05), (0.2, 0.17, 0.09)])
    nt.links.new(tex.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    bsdf.inputs["Roughness"].default_value = 0.95
    return m
