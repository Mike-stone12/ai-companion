import importlib.util
import sys
from pathlib import Path

import pytest

import companion.env

SOURCE_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def load_paths(monkeypatch):
    loaded_env_paths = []
    monkeypatch.setattr(companion.env, "load_local_env", loaded_env_paths.append)

    def load():
        # Isolate import-time constants without changing modules used by other tests.
        spec = importlib.util.spec_from_file_location("isolated_paths", SOURCE_ROOT / "companion" / "paths.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        assert loaded_env_paths[-1] == module.ENV_PATH
        return module

    return load


def assert_resources(paths, root):
    assert paths.APP_DIR == root
    assert paths.HTML_PATH == root / "live2d_renderer.html"
    assert paths.MODELS_DIR == root / "models"
    assert paths.VENDOR_DIR == root / "vendor"


@pytest.mark.parametrize("frozen", [None, False])
def test_non_frozen_paths_use_source_checkout(monkeypatch, tmp_path, load_paths, frozen):
    monkeypatch.delattr(sys, "frozen", raising=False)
    if frozen is not None:
        monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    paths = load_paths()

    assert_resources(paths, SOURCE_ROOT)
    assert paths.ENV_PATH == SOURCE_ROOT / ".env"


def test_frozen_resources_use_bundle(monkeypatch, tmp_path, load_paths):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert_resources(load_paths(), tmp_path)


@pytest.mark.parametrize("has_bundle", [False, True])
def test_frozen_env_is_beside_executable(monkeypatch, tmp_path, load_paths, has_bundle):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    if has_bundle:
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "companion.exe"))

    assert load_paths().ENV_PATH == tmp_path / "app" / ".env"


def test_frozen_without_bundle_uses_source_resources(monkeypatch, load_paths):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assert_resources(load_paths(), SOURCE_ROOT)


def test_helpers_read_frozen_state_at_call_time(monkeypatch, tmp_path, load_paths):
    monkeypatch.delattr(sys, "frozen", raising=False)
    paths = load_paths()
    assert paths.resource_root() == SOURCE_ROOT
    assert paths.local_env_path() == SOURCE_ROOT / ".env"

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "companion.exe"))

    assert paths.resource_root() == tmp_path / "bundle"
    assert paths.local_env_path() == tmp_path / "app" / ".env"


def test_frozen_user_data_paths_are_unchanged(monkeypatch, tmp_path, load_paths):
    monkeypatch.delattr(sys, "frozen", raising=False)
    source_paths = load_paths()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    frozen_paths = load_paths()

    for name in ("DATA_DIR", "MEMORY_PATH", "HISTORY_PATH", "CONFIG_PATH", "LOG_DIR"):
        assert getattr(frozen_paths, name) == getattr(source_paths, name)
