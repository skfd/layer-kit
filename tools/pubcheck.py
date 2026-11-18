"""Dry-check a layer's publish wiring: record what git would be run with.

usage (from a layer checkout): python pubcheck.py
Stands in for src.publish._git, so nothing is staged, committed or pushed.
"""
import os
import sys

sys.path.insert(0, os.getcwd())
from src import config, publish as pub  # noqa: E402

calls = []


def fake_git(args, env):
    calls.append((args[0], env["GIT_DIR"], env["GIT_WORK_TREE"], env["GIT_INDEX_FILE"]))
    if args[0] == "add":
        open(env["GIT_INDEX_FILE"], "w").close()
    return "0" * 40 + "\n"


pub._git = fake_git
pub.publish()
want = (os.path.join(config.PROJECT_DIR, ".git"), config.SITE_DIR,
        os.path.join(config.BUILD_DIR, ".gh-pages-index"))
assert [c[0] for c in calls] == ["add", "write-tree", "commit-tree", "update-ref", "push"], calls
assert all(c[1:] == want for c in calls), (calls, want)
assert os.path.isdir(os.path.join(want[0])), "GIT_DIR is not a repo"
assert not os.path.exists(want[2]), "index left behind"
print("publish wiring ok:", os.path.basename(config.PROJECT_DIR), "->", want[1])
