"""Bounded, non-interactive Git operations for the data repository."""

import logging
import os
import subprocess
from pathlib import Path


class Git:
    def __init__(self, repo_path: str, branch: str, timeout: int = 120) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.branch = branch
        self.timeout = timeout
        self.logger = logging.getLogger(self.__class__.__name__)

    def _run(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        command = ["git", *args]
        environment = os.environ.copy()
        environment.update({"GIT_TERMINAL_PROMPT": "0", "GCM_INTERACTIVE": "Never"})
        try:
            result = subprocess.run(
                command,
                cwd=self.repo_path,
                check=check,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                env=environment,
            )
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"git {' '.join(args)} timed out") from error
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "").strip().splitlines()
            suffix = f": {detail[-1][:300]}" if detail else ""
            raise RuntimeError(f"git {' '.join(args)} failed{suffix}") from error
        return result

    def _verify_repository(self) -> None:
        if not self.repo_path.is_dir():
            raise RuntimeError(f"Git repository does not exist: {self.repo_path}")
        top = Path(self._run("rev-parse", "--show-toplevel").stdout.strip()).resolve()
        if top != self.repo_path:
            raise RuntimeError(f"Git path is not a dedicated repository: {self.repo_path}")

    def sync(self) -> None:
        """Make the dedicated checkout exactly match the fetched cloud branch."""
        self._verify_repository()
        self.logger.info("Fetching origin/%s before cloud-authoritative sync", self.branch)
        remote_refspec = f"+refs/heads/{self.branch}:refs/remotes/origin/{self.branch}"
        self._run("fetch", "--prune", "origin", remote_refspec)
        remote_ref = f"refs/remotes/origin/{self.branch}"
        self._run("show-ref", "--verify", remote_ref)
        self._run("reset", "--hard")
        self._run("checkout", "-B", self.branch, remote_ref)
        self._run("reset", "--hard", remote_ref)
        self._run("clean", "-fd")
        self.logger.info("Synchronized checkout to origin/%s", self.branch)

    def push(self) -> None:
        """Commit generated data and publish only if the remote is unchanged."""
        self._verify_repository()
        current = self._run("branch", "--show-current").stdout.strip()
        if current != self.branch:
            raise RuntimeError(f"Cannot publish from branch {current!r}; expected {self.branch!r}")
        if self._run("rev-parse", "--verify", "MERGE_HEAD", check=False).returncode == 0:
            raise RuntimeError("Cannot publish with an unresolved merge state")
        self._run("add", ".")
        status = self._run("status", "--porcelain").stdout.strip()
        if status:
            self._run("commit", "-m", "Update")
        self._run("push", "--porcelain", "origin", f"HEAD:{self.branch}")
