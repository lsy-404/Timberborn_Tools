import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from util.git import Git


def run_git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "commit.gpgSign",
            "GIT_CONFIG_VALUE_0": "false",
        },
        timeout=30,
    )


class GitSyncTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.remote = self.root / "remote.git"
        run_git(self.root, "init", "--bare", "--initial-branch=main", str(self.remote))
        self.seed = self.root / "seed"
        run_git(self.root, "clone", str(self.remote), str(self.seed))
        run_git(self.seed, "config", "user.name", "Test User")
        run_git(self.seed, "config", "user.email", "test@example.invalid")
        (self.seed / "tracked.txt").write_text("initial\n", encoding="utf-8")
        (self.seed / ".gitignore").write_text("ignored.txt\n", encoding="utf-8")
        run_git(self.seed, "add", "-f", ".gitignore", "tracked.txt")
        run_git(self.seed, "commit", "-m", "initial")
        run_git(self.seed, "branch", "-M", "main")
        run_git(self.seed, "push", "-u", "origin", "main")
        self.repo = self.root / "repo"
        run_git(self.root, "clone", str(self.remote), str(self.repo))
        run_git(self.repo, "config", "user.name", "Test User")
        run_git(self.repo, "config", "user.email", "test@example.invalid")
        run_git(self.repo, "branch", "--set-upstream-to", "origin/main", "main")
        self.git = Git(str(self.repo), "main", timeout=10)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def remote_commit(self, name: str, content: str) -> None:
        (self.seed / name).write_text(content, encoding="utf-8")
        run_git(self.seed, "add", name)
        run_git(self.seed, "commit", "-m", f"remote {name}")
        run_git(self.seed, "push", "origin", "main")

    def test_sync_resolves_unmerged_state_and_divergence(self) -> None:
        (self.repo / "tracked.txt").write_text("local\n", encoding="utf-8")
        run_git(self.repo, "add", "tracked.txt")
        run_git(self.repo, "commit", "-m", "local")
        self.remote_commit("tracked.txt", "remote\n")
        run_git(self.repo, "fetch", "origin", "main")
        run_git(self.repo, "merge", "origin/main", check=False)
        self.assertTrue((self.repo / ".git" / "MERGE_HEAD").exists())
        self.git.sync()
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())
        self.assertEqual(run_git(self.repo, "rev-parse", "HEAD").stdout, run_git(self.seed, "rev-parse", "HEAD").stdout)
        self.assertEqual((self.repo / "tracked.txt").read_text(encoding="utf-8"), "remote\n")

    def test_sync_cleans_dirty_and_untracked_but_preserves_ignored(self) -> None:
        (self.repo / "tracked.txt").write_text("dirty\n", encoding="utf-8")
        (self.repo / "untracked.txt").write_text("remove\n", encoding="utf-8")
        (self.repo / "ignored.txt").write_text("preserve\n", encoding="utf-8")
        self.assertEqual(run_git(self.repo, "check-ignore", "ignored.txt").stdout.strip(), "ignored.txt")
        self.git.sync()
        self.assertEqual((self.repo / "tracked.txt").read_text(encoding="utf-8"), "initial\n")
        self.assertFalse((self.repo / "untracked.txt").exists())
        self.assertEqual((self.repo / "ignored.txt").read_text(encoding="utf-8"), "preserve\n")

    def test_sync_returns_to_configured_branch(self) -> None:
        run_git(self.repo, "switch", "-c", "other")
        self.git.sync()
        self.assertEqual(run_git(self.repo, "branch", "--show-current").stdout.strip(), "main")

    def test_sync_refreshes_tracking_ref_with_restricted_fetch_mapping(self) -> None:
        self.git.sync()
        self.remote_commit("fresh.txt", "fresh\n")
        run_git(
            self.repo,
            "config",
            "remote.origin.fetch",
            "+refs/heads/other:refs/remotes/origin/other",
        )
        self.git.sync()
        self.assertEqual(
            run_git(self.repo, "rev-parse", "HEAD").stdout,
            run_git(self.seed, "rev-parse", "HEAD").stdout,
        )
        self.assertEqual((self.repo / "fresh.txt").read_text(encoding="utf-8"), "fresh\n")

    def test_failed_fetch_preserves_prefetch_state(self) -> None:
        before_head = run_git(self.repo, "rev-parse", "HEAD").stdout
        (self.repo / "tracked.txt").write_text("local state\n", encoding="utf-8")
        before_status = run_git(self.repo, "status", "--porcelain").stdout
        run_git(self.repo, "remote", "set-url", "origin", str(self.root / "missing.git"))
        with self.assertRaises(RuntimeError):
            self.git.sync()
        self.assertEqual(run_git(self.repo, "rev-parse", "HEAD").stdout, before_head)
        self.assertEqual(run_git(self.repo, "status", "--porcelain").stdout, before_status)
        self.assertEqual((self.repo / "tracked.txt").read_text(encoding="utf-8"), "local state\n")

    def test_push_publishes_generated_data(self) -> None:
        self.git.sync()
        (self.repo / "generated.txt").write_text("generated\n", encoding="utf-8")
        self.git.push()
        check = self.root / "check"
        run_git(self.root, "clone", str(self.remote), str(check))
        self.assertEqual((check / "generated.txt").read_text(encoding="utf-8"), "generated\n")

    def test_push_rejects_remote_advance_without_merge_state(self) -> None:
        self.git.sync()
        (self.repo / "generated.txt").write_text("local\n", encoding="utf-8")
        other = self.root / "other"
        run_git(self.root, "clone", str(self.remote), str(other))
        run_git(other, "config", "user.name", "Test User")
        run_git(other, "config", "user.email", "test@example.invalid")
        (other / "remote.txt").write_text("remote\n", encoding="utf-8")
        run_git(other, "add", "remote.txt")
        run_git(other, "commit", "-m", "advance")
        run_git(other, "push", "origin", "main")
        with self.assertRaises(RuntimeError):
            self.git.push()
        self.assertFalse((self.repo / ".git" / "MERGE_HEAD").exists())


if __name__ == "__main__":
    unittest.main()
