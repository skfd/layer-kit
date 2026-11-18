"""Publish a built site to the orphan gh-pages branch (single commit, force-push).

A tile pyramid is tens to hundreds of thousands of files. To avoid copying
them all into a worktree, this stages them in place with a temporary index and
GIT_WORK_TREE, builds an orphan commit with git plumbing, and force-pushes it.
Each publish replaces the branch tip, so repository history never grows.

Every path is an argument, resolved when ``publish`` is called: a wrong one
here force-pushes the wrong tree over a live site.
"""

import os
import re
import subprocess
import time
from datetime import date

from addressvault import net

# Publishing is the last step of a long build, so a blip here is the most
# expensive failure there is: the streets layer lost a finished 150k-tile
# pyramid on 2026-07-27 to a push that could not resolve github.com. Retry the
# push rather than the build.
PUSH_RETRIES = 2
PUSH_WAIT = 300
# Only network failures are worth retrying. A rejected push or a bad credential
# fails the same way every time, and should surface now instead of ten minutes
# from now.
_NETWORK_ERR = re.compile(
    r"could not resolve host|unable to access|failed to connect"
    r"|connection timed out|operation timed out|connection reset",
    re.I,
)


def publish(project_dir, site_dir, build_dir, *, git=None, push_fn=None):
    """Commit ``site_dir`` as a single orphan commit on gh-pages and force-push.

    ``git(args, env)`` and ``push_fn(env)`` default to ``run_git`` in
    ``project_dir`` and ``push``; a layer passes its own wrappers so its tests
    can stand in for them.
    """
    if not os.path.isdir(site_dir):
        raise RuntimeError(f"No site to publish: {site_dir}. Run 'site' first.")
    if git is None:
        def git(args, env):
            return run_git(project_dir, args, env)
    if push_fn is None:
        def push_fn(env):
            return push(env, git=git)

    index = os.path.join(build_dir, ".gh-pages-index")
    env = {
        **os.environ,
        "GIT_DIR": os.path.join(project_dir, ".git"),
        "GIT_WORK_TREE": site_dir,
        "GIT_INDEX_FILE": index,
    }
    if os.path.exists(index):
        os.remove(index)

    print("Staging site files ...")
    git(["add", "-A"], env)
    tree = git(["write-tree"], env).strip()
    commit = git(
        ["commit-tree", tree, "-m", f"site {date.today().isoformat()}"], env
    ).strip()
    git(["update-ref", "refs/heads/gh-pages", commit], env)

    print("Force-pushing gh-pages ...")
    push_fn(env)

    os.remove(index)
    print("Published to the gh-pages branch.")


def push(env, *, git, retries=PUSH_RETRIES, wait=PUSH_WAIT):
    """Force-push gh-pages, retrying a network failure.

    The commit is already written to refs/heads/gh-pages locally by the time we
    get here, so a retry costs one round-trip -- and giving up leaves the build
    on disk for a later ``run.py publish`` rather than requiring a rebuild.
    Raises ``net.LinkUnavailable`` if the link is what died, so the caller can
    exit 75: an unreachable github.com is not a failed build.
    """
    for attempt in range(retries + 1):
        try:
            git(["push", "--force", "origin", "gh-pages"], env)
            return
        except RuntimeError as e:
            if not _NETWORK_ERR.search(str(e)):
                raise
            if attempt == retries:
                net.wait_for_link(wait=False)
                raise
            print(f"  push failed ({e.args[0].splitlines()[-1]});"
                  f" retrying in {wait}s")
            time.sleep(wait)


def run_git(project_dir, args, env):
    """Run git in ``project_dir``; return stdout, raise RuntimeError on failure."""
    result = subprocess.run(
        ["git", *args],
        cwd=project_dir,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        env=env,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} failed (exit {result.returncode}):\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout
