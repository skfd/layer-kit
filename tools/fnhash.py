"""Hash every top-level function of src/*.py across the layer repos.

Prints, per (file, function), how many distinct bodies exist and which repos
share each. Read-only.
"""
import ast
import hashlib
import os
import sys
from collections import defaultdict

root = sys.argv[1]
repos = sorted(d for d in os.listdir(root)
               if d.endswith("-layer") and os.path.isdir(os.path.join(root, d, "src")))
table = defaultdict(lambda: defaultdict(list))   # (file, fn) -> hash -> [repo]
sizes = {}
for repo in repos:
    src = os.path.join(root, repo, "src")
    for name in sorted(os.listdir(src)):
        if not name.endswith(".py"):
            continue
        text = open(os.path.join(src, name), encoding="utf-8").read()
        try:
            tree = ast.parse(text)
        except SyntaxError as e:
            print("SYNTAX", repo, name, e)
            continue
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                body = ast.get_source_segment(text, node)
                h = hashlib.sha1(body.encode()).hexdigest()[:6]
                table[(name, node.name)][h].append(repo)
                sizes[(name, node.name, h)] = body.count("\n") + 1

short = {r: r.replace("-layer", "").replace("guelph-", "g.").replace("toronto-", "t.")
         for r in repos}
print(len(repos), "repos:", " ".join(short.values()))
for (name, fn), variants in sorted(table.items()):
    n = sum(len(v) for v in variants.values())
    if n < 3:
        continue
    parts = []
    for h, rs in sorted(variants.items(), key=lambda kv: -len(kv[1])):
        parts.append(f"{len(rs)}x{sizes[(name, fn, h)]}L[{','.join(short[r] for r in rs)}]"
                     if len(variants) > 1 and len(rs) < 6 else f"{len(rs)}x{sizes[(name, fn, h)]}L")
    print(f"{name:12} {fn:24} in {n:2} repos, {len(variants)} variant(s): {' '.join(parts)}")
