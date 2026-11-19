"""Shared deployment configuration: env-file loading and output directory.

The server normally reads `.env` from the checkout and writes to `./outputs`,
which breaks when the same repository has several git worktrees (each checkout
would need its own copy). These helpers let the deployment point every worktree
at one config file and one data directory.
"""
from __future__ import annotations

import os
from pathlib import Path

from deepchoice.server import app as app_module
from deepchoice.server import env_config, snapshot_store


def test_output_dir_defaults_to_relative_outputs(monkeypatch):
    monkeypatch.delenv("DEEPCHOICE_OUTPUT_DIR", raising=False)
    assert env_config.output_dir() == Path("./outputs")


def test_output_dir_honours_the_environment(monkeypatch, tmp_path):
    shared = tmp_path / "shared-outputs"
    monkeypatch.setenv("DEEPCHOICE_OUTPUT_DIR", str(shared))
    assert env_config.output_dir() == shared


def test_env_file_path_is_none_when_unset(monkeypatch):
    monkeypatch.delenv("DEEPCHOICE_ENV_FILE", raising=False)
    assert env_config.env_file_path() is None


def test_env_file_path_honours_the_environment(monkeypatch, tmp_path):
    env_file = tmp_path / "shared.env"
    monkeypatch.setenv("DEEPCHOICE_ENV_FILE", str(env_file))
    assert env_config.env_file_path() == str(env_file)


def test_load_environment_uses_the_explicit_file(tmp_path, monkeypatch):
    env_file = tmp_path / "shared.env"
    env_file.write_text("DEEPCHOICE_TEST_SHARED_VALUE=from-explicit-file\n",
                        encoding="utf-8")
    monkeypatch.setenv("DEEPCHOICE_ENV_FILE", str(env_file))
    monkeypatch.delenv("DEEPCHOICE_TEST_SHARED_VALUE", raising=False)

    assert env_config.load_environment() is True
    assert os.environ["DEEPCHOICE_TEST_SHARED_VALUE"] == "from-explicit-file"


def test_app_and_snapshot_store_use_the_shared_resolution():
    """Both modules must resolve the same output directory at import time."""
    assert snapshot_store.OUTPUT_DIR == env_config.output_dir()
    assert app_module.OUTPUT_DIR == env_config.output_dir()
