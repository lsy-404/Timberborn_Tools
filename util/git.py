"""
version: 1.0.0
author: Wuyilingwei
This module provides git actions
This module is used to push and pull git repository
"""
import os
import logging
import subprocess

class Git:
    """
    Git class to handle git operations
    """
    def __init__(self, repo_path: str, branch: str) -> None:
        """
        Initialize the Git class with the repository path
        """
        self.repo_path = repo_path
        self.branch = branch
        self.logger = logging.getLogger(self.__class__.__name__)

    def push(self) -> None:
        """
        Push changes to the remote repository
        """
        try:
            self.logger.info("Pushing changes to remote repository")

            # Ensure we're on the correct branch
            subprocess.run(['git', 'checkout', self.branch], cwd=self.repo_path, check=True)
            subprocess.run(['git', 'add', '.'], cwd=self.repo_path, check=True)

            # Check if there are changes to commit
            status = subprocess.run(['git', 'status', '--porcelain'], cwd=self.repo_path, capture_output=True, text=True, check=True)
            if not status.stdout.strip():
                self.logger.info("Nothing to commit, working tree clean")
            else:
                subprocess.run(['git', 'commit', '-m', 'Update'], cwd=self.repo_path, check=True)

            subprocess.run(['git', 'push', 'origin', self.branch], cwd=self.repo_path, check=True)
            self.logger.info("Changes pushed successfully")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error pushing changes: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")

    def pull(self) -> None:
        """
        Pull changes from the remote repository
        """
        try:
            self.logger.info("Pulling changes from remote repository")
            subprocess.run(['git', 'checkout', self.branch], cwd=self.repo_path, check=True)
            subprocess.run(['git', 'pull', 'origin', self.branch], cwd=self.repo_path, check=True)
            self.logger.info("Changes pulled successfully")
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Error pulling changes: {e}")
        except Exception as e:
            self.logger.error(f"Unexpected error: {e}")