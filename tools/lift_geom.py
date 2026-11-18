"""Replace a layer's copies of the shared geometry helpers with layerkit.geom.

usage: lift_geom.py REPO_DIR

A helper is lifted only when the layer's copy is the same code as the kit's
(compared as syntax trees, so a docstring or comment may differ). Anything
else is left alone and reported. Line endings are preserved.
"""
import ast
import os
import sys

import layerkit.geom

repo = os.path.abspath(sys.argv[1])
path = os.path.join(repo, "src", "compare.py")
NAMES = ("dist", "bbox_overlap", "point_in_ring", "relation_outer_loops")

with open(layerkit.geom.__file__, encoding="utf-8") as f:
    kit = {n.name: n for n in ast.parse(f.read()).body if isinstance(n, ast.FunctionDef)}


def shape(node, rename):
    """The function as a dump with its docstring dropped and names unified."""
    node = ast.parse(ast.unparse(node)).body[0]
    if (node.body and isinstance(node.body[0], ast.Expr)
            and isinstance(node.body[0].value, ast.Constant)
            and isinstance(node.body[0].value.value, str)):
        node.body = node.body[1:]
    node.name = rename
    return ast.dump(node)


with open(path, encoding="utf-8", newline="") as f:
    raw = f.read()
eol = "\r\n" if "\r\n" in raw else "\n"
text = raw.replace("\r\n", "\n")

lifted = []
for name in NAMES:
    local = "_" + name
    nodes = {n.name: n for n in ast.parse(text).body if isinstance(n, ast.FunctionDef)}
    node = nodes.get(local)
    if node is None:
        continue
    if shape(node, name) != shape(kit[name], name):
        print(f"  {local}: differs from the kit's, left alone")
        continue
    lines = text.split("\n")
    start, end = node.lineno - 1, node.end_lineno
    while end < len(lines) and not lines[end].strip():
        end += 1
    del lines[start:end]
    text = "\n".join(lines)
    lifted.append(name)

if lifted:
    anchor = "from layerkit import overpass\n"
    if text.count(anchor) != 1:
        raise SystemExit(f"{os.path.basename(repo)}: no single {anchor!r}")
    imports = "".join(f"from layerkit.geom import {n} as _{n}\n" for n in lifted)
    text = text.replace(anchor, imports + anchor)
    # A helper the lifted code was the only user of is now dead.
    tree = ast.parse(text)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_pt" and "_pt" not in used:
            lines = text.split("\n")
            start, end = n.lineno - 1, n.end_lineno
            while end < len(lines) and not lines[end].strip():
                end += 1
            del lines[start:end]
            text = "\n".join(lines)
            lifted.append("(dropped _pt, now unused)")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text.rstrip("\n").replace("\n", eol) + eol)
print(os.path.basename(repo), "lifted:", ", ".join(lifted) or "nothing")
