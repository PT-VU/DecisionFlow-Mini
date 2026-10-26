from pathlib import Path

import pytest

from local_bridge.security import ensure_allowed_task, resolve_workspace


def test_bridge_rejects_arbitrary_task_type():
    with pytest.raises(ValueError):
        ensure_allowed_task("run_shell_command")


def test_bridge_rejects_workspace_escape(tmp_path):
    with pytest.raises(ValueError):
        resolve_workspace(tmp_path, "..")
