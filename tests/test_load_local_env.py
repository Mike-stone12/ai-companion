import os

import pytest

from companion.env import load_local_env

TEST_KEYS = ("COMPANION_TEST_MODEL", "COMPANION_TEST_A", "COMPANION_TEST_B")


@pytest.fixture(autouse=True)
def clean_test_keys():
    saved = {key: os.environ.pop(key) for key in TEST_KEYS if key in os.environ}
    yield
    for key in TEST_KEYS:
        os.environ.pop(key, None)
    os.environ.update(saved)


def write_env(tmp_path, content):
    env_file = tmp_path / ".env"
    env_file.write_text(content, encoding="utf-8")
    return env_file


def test_existing_environment_variable_wins(tmp_path):
    os.environ["COMPANION_TEST_MODEL"] = "from-shell"
    load_local_env(write_env(tmp_path, "COMPANION_TEST_MODEL=from-dotenv\n"))
    assert os.environ["COMPANION_TEST_MODEL"] == "from-shell"


def test_missing_variables_are_loaded_and_unquoted(tmp_path):
    content = '# comment\n\nCOMPANION_TEST_A="quoted value"\nCOMPANION_TEST_B = plain\nnot a pair\n'
    load_local_env(write_env(tmp_path, content))
    assert os.environ["COMPANION_TEST_A"] == "quoted value"
    assert os.environ["COMPANION_TEST_B"] == "plain"


def test_missing_file_is_ignored(tmp_path):
    load_local_env(tmp_path / "does-not-exist.env")
