"""The publish step: the push retry, and which tree is pushed where.

The push is the last thing in a long build, so the retry covers the failure
that costs the most: a finished tile pyramid thrown away by a resolver blip.
The paths matter as much -- a wrong one force-pushes over a live site.
"""

import os

import pytest
from addressvault import net

from layerkit import publish as pub

RESOLVER_FAILURE = (
    "git push --force origin gh-pages failed (exit 128):\n"
    "fatal: unable to access 'https://github.com/x/y.git/': "
    "Could not resolve host: github.com"
)
REJECTED = (
    "git push --force origin gh-pages failed (exit 1):\n"
    " ! [rejected] gh-pages -> gh-pages (non-fast-forward)"
)


@pytest.fixture(autouse=True)
def usable_link(monkeypatch):
    monkeypatch.setattr("addressvault.net.wait_for_link", lambda **k: None)


def failing_git(calls, message, fail_times=99):
    def git(args, env):
        calls.append(args)
        if len(calls) <= fail_times:
            raise RuntimeError(message)
        return ""
    return git


def test_a_resolver_failure_is_retried():
    calls = []
    pub.push({}, git=failing_git(calls, RESOLVER_FAILURE, fail_times=2), wait=0)
    assert len(calls) == 3  # two blips, then through


def test_a_rejected_push_is_not_retried():
    calls = []
    with pytest.raises(RuntimeError):
        pub.push({}, git=failing_git(calls, REJECTED), wait=0)
    assert len(calls) == 1


def test_offline_at_the_push_surfaces_as_link_unavailable(monkeypatch):
    calls = []
    monkeypatch.setattr(
        "addressvault.net.wait_for_link",
        lambda **k: (_ for _ in ()).throw(net.Offline("link is offline")),
    )
    with pytest.raises(net.Offline):
        pub.push({}, git=failing_git(calls, RESOLVER_FAILURE), wait=0)
    assert len(calls) == pub.PUSH_RETRIES + 1


def test_publish_stages_the_site_dir_against_the_projects_git_dir(tmp_path):
    project, site, build = tmp_path / "p", tmp_path / "p" / "build" / "site", tmp_path / "p" / "build"
    site.mkdir(parents=True)
    seen = []

    def git(args, env):
        seen.append((args[0], env["GIT_DIR"], env["GIT_WORK_TREE"], env["GIT_INDEX_FILE"]))
        open(env["GIT_INDEX_FILE"], "w").close()
        return "abc123\n"

    pushed = []
    pub.publish(str(project), str(site), str(build), git=git, push_fn=pushed.append)

    index = os.path.join(str(build), ".gh-pages-index")
    assert [s[0] for s in seen] == ["add", "write-tree", "commit-tree", "update-ref"]
    assert {s[1:] for s in seen} == {(os.path.join(str(project), ".git"), str(site), index)}
    assert len(pushed) == 1
    assert not os.path.exists(index)


def test_publish_refuses_when_there_is_no_site(tmp_path):
    with pytest.raises(RuntimeError, match="No site to publish"):
        pub.publish(str(tmp_path), str(tmp_path / "site"), str(tmp_path))
