#!/usr/bin/env python3
"""check_bpy - catch Blender Python API mistakes before a render is wasted.

Type-checks Blender scripts against fake-bpy-module (MIT, nutti/fake-bpy-module:
stub files of the whole bpy API) with mypy, and keeps only the errors that would
crash Blender: misspelled or removed attributes, wrong keyword arguments,
undefined names. Generic-type noise (e.g. constraints.new() typed as the base
Constraint class) is filtered out.

  pip install fake-bpy-module mypy
  python check_bpy.py script.py [more.py ...]      exit code 1 if problems found
"""
import re
import subprocess
import sys

KEEP = ("attr-defined", "call-arg", "name-defined", "call-overload")
# bpy factory methods return a base class; attributes of the real subclass are fine
BASES = {"Constraint", "Curve", "Attribute", "Modifier", "Node", "NodeSocket", "ID",
         "Light", "Camera", "Texture", "ShaderNode", "GeometryNode", "FCurveModifier",
         "Sequence", "Strip", "Effect", "GreasePencil", "Action", "AnyType",
         "NodeTree", "bpy_struct", "Operator", "Panel", "Property", "Gizmo",
         "AttributeGroup", "ParticleSettings", "Object", "Mesh", "Material", "World"}
LINE = re.compile(r"^(?P<file>.+?):(?P<line>\d+): error: (?P<msg>.*)  \[(?P<code>[\w-]+)\]$")
ATTR = re.compile(r'^"(?P<type>[^"]+)" has no attribute "(?P<attr>\w+)"(?P<hint>; maybe .*)?$')


def check(paths):
    cmd = [sys.executable, "-m", "mypy", "--ignore-missing-imports", "--check-untyped-defs",
           "--show-error-codes", "--no-error-summary", "--no-color-output", "--follow-imports=silent"]
    res = subprocess.run(cmd + list(paths), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if "No module named mypy" in res.stdout:
        sys.exit("check_bpy: run  pip install fake-bpy-module mypy")
    found = []
    for raw in res.stdout.splitlines():
        m = LINE.match(raw.strip())
        if not m or m.group("code") not in KEEP:
            continue
        a = ATTR.match(m.group("msg"))
        if a and not a.group("hint") and a.group("type").split(".")[-1] in BASES:
            continue
        if a and re.match(r"(builtins\.)?(float|int|str|bool|tuple|list|dict|set)\b", a.group("type")):
            continue                     # a reused local variable, not a bpy mistake
        if m.group("code") == "call-overload" and "bpy" not in m.group("msg"):
            continue
        found.append("%s:%s: %s" % (m.group("file"), m.group("line"), m.group("msg")))
    return found


def main():
    paths = sys.argv[1:]
    if not paths:
        sys.exit(__doc__)
    found = check(paths)
    for f in found:
        print(f)
    print("check_bpy: %d problem(s) in %d file(s)" % (len(found), len(paths)))
    sys.exit(1 if found else 0)


if __name__ == "__main__":
    main()
