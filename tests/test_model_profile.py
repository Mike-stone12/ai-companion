import json

from main import DEFAULT_MODEL, DEFAULT_WINDOW_SIZE, discover_model_profile, load_model_profile


def make_model(models_dir, name, model_file="avatar.model3.json", companion=None):
    model_dir = models_dir / name
    model_dir.mkdir(parents=True)
    (model_dir / model_file).write_text("{}", encoding="utf-8")
    if companion is not None:
        text = companion if isinstance(companion, str) else json.dumps(companion)
        (model_dir / "companion.json").write_text(text, encoding="utf-8")
    return model_dir


def test_profile_reads_companion_json(tmp_path):
    model_dir = make_model(
        tmp_path,
        "whale",
        model_file="c_0120.model3.json",
        companion={
            "model": "c_0120.model3.json",
            "window": {"width": 400, "height": 500},
            "motions": {"talk": ["selfie"], "ambient": ["bubble", "splash"]},
        },
    )
    profile = load_model_profile(model_dir)
    assert profile.path == (model_dir / "c_0120.model3.json").resolve()
    assert profile.window_size == (400, 500)
    assert profile.motions == {"talk": ["selfie"], "ambient": ["bubble", "splash"]}


def test_profile_without_companion_json_uses_defaults(tmp_path):
    model_dir = make_model(tmp_path, "plain")
    profile = load_model_profile(model_dir)
    assert profile.path == (model_dir / "avatar.model3.json").resolve()
    assert profile.window_size == DEFAULT_WINDOW_SIZE
    assert profile.motions == {}


def test_profile_from_model_file_reads_sibling_companion_json(tmp_path):
    model_dir = make_model(tmp_path, "whale", companion={"window": {"width": 300, "height": 300}})
    profile = load_model_profile(model_dir / "avatar.model3.json")
    assert profile.window_size == (300, 300)


def test_invalid_companion_json_falls_back_to_defaults(tmp_path):
    model_dir = make_model(tmp_path, "broken", companion="{not json")
    profile = load_model_profile(model_dir)
    assert profile.path.name == "avatar.model3.json"
    assert profile.window_size == DEFAULT_WINDOW_SIZE


def test_malformed_fields_are_ignored(tmp_path):
    model_dir = make_model(
        tmp_path,
        "odd",
        companion={"window": {"width": "wide"}, "motions": {"talk": "selfie", "ambient": ["ok", 3]}},
    )
    profile = load_model_profile(model_dir)
    assert profile.window_size == DEFAULT_WINDOW_SIZE
    assert profile.motions == {"ambient": ["ok"]}


def test_directory_without_model_file_has_no_profile(tmp_path):
    (tmp_path / "empty").mkdir()
    assert load_model_profile(tmp_path / "empty") is None


def test_discover_defaults_to_default_model(tmp_path):
    make_model(tmp_path, "aaa-first-alphabetically")
    default_dir = make_model(tmp_path, DEFAULT_MODEL)
    assert discover_model_profile("", tmp_path).path.parent == default_dir.resolve()


def test_discover_by_folder_name(tmp_path):
    make_model(tmp_path, DEFAULT_MODEL)
    hiyori_dir = make_model(tmp_path, "hiyori")
    assert discover_model_profile("hiyori", tmp_path).path.parent == hiyori_dir.resolve()


def test_discover_by_explicit_path(tmp_path):
    custom_dir = make_model(tmp_path / "elsewhere", "custom")
    profile = discover_model_profile(str(custom_dir / "avatar.model3.json"), tmp_path / "models")
    assert profile.path.parent == custom_dir.resolve()


def test_discover_unknown_name_falls_back_to_default(tmp_path):
    default_dir = make_model(tmp_path, DEFAULT_MODEL)
    assert discover_model_profile("missing", tmp_path).path.parent == default_dir.resolve()


def test_discover_without_default_uses_first_available(tmp_path):
    only_dir = make_model(tmp_path, "hiyori")
    assert discover_model_profile("", tmp_path).path.parent == only_dir.resolve()


def test_discover_with_no_models_returns_none(tmp_path):
    assert discover_model_profile("", tmp_path / "nothing-here") is None
