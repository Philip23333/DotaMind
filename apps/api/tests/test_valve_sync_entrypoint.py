from __future__ import annotations

import ast
import hashlib
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.integrations.valve import game_data_sync

API_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = API_ROOT / "scripts" / "sync_game_data.py"


def test_application_module_import_is_independent_and_has_no_io_side_effects(
    tmp_path: Path,
) -> None:
    code = """
import pathlib
import tempfile
import urllib.request
from app.integrations.valve import datafeed

def forbidden(*args, **kwargs):
    raise AssertionError("import caused an external or filesystem side effect")

import sys

datafeed.ValveDatafeedClient = forbidden
tempfile.mkdtemp = forbidden
pathlib.Path.mkdir = forbidden
pathlib.Path.write_text = forbidden
pathlib.Path.write_bytes = forbidden
urllib.request.urlopen = forbidden

import app.integrations.valve.game_data_sync as sync
assert callable(sync.main)
assert not any(
    name == "scripts" or name.startswith("scripts.") for name in sys.modules
)
print("imported")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(API_ROOT), env.get("PYTHONPATH", "")) if part
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "imported"


def test_module_and_legacy_script_help_work_from_different_directories(
    tmp_path: Path,
) -> None:
    module_help = subprocess.run(
        [sys.executable, "-m", "app.integrations.valve.game_data_sync", "--help"],
        cwd=API_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    script_help = subprocess.run(
        [sys.executable, str(SCRIPT_PATH), "--help"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert module_help.returncode == 0, module_help.stderr
    assert script_help.returncode == 0, script_help.stderr
    def normalize_prog(value: str) -> str:
        return value.replace("game_data_sync.py", "ENTRY.py").replace(
            "sync_game_data.py", "ENTRY.py"
        )

    assert normalize_prog(module_help.stdout) == normalize_prog(script_help.stdout)
    assert "--patch PATCH" in module_help.stdout
    assert "--workers WORKERS" in module_help.stdout
    assert "--images-only" in module_help.stdout


def test_sync_defaults_and_output_paths_are_independent_of_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    default_patch_output = game_data_sync.PATCH_OUTPUT_DIR
    bundle = SimpleNamespace(
        abilities=[SimpleNamespace(ability_id=10, name_en="Ability", name_zh="技能")],
        heroes=[object()],
        items=[object()],
    )
    fake_client = object()
    fake_session = object()
    calls: dict[str, object] = {}

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(game_data_sync, "ValveDatafeedClient", lambda: fake_client)

    def make_session(client: object, *, max_concurrency: int) -> object:
        calls["session"] = (client, max_concurrency)
        return fake_session

    monkeypatch.setattr(game_data_sync, "ValveFetchSession", make_session)
    monkeypatch.setattr(
        game_data_sync,
        "_load_committed_catalog_bundle",
        lambda: SimpleNamespace(abilities=[SimpleNamespace(ability_id=1)]),
    )

    def latest_patch(client: object) -> str:
        calls["latest_client"] = client
        return "7.41f"

    def build_catalog(client: object, patch: str, *, workers: int):
        calls["catalog"] = (client, patch, workers)
        return bundle

    def sync_images(received_bundle: object, *, workers: int) -> int:
        calls["images"] = (received_bundle, workers)
        return 0

    def write_catalog(received_bundle: object) -> None:
        calls["write"] = received_bundle

    def build_patch(client: object, patch: str) -> dict[str, object]:
        calls["patch"] = (client, patch)
        return {"changes": []}

    monkeypatch.setattr(game_data_sync, "_latest_patch", latest_patch)
    monkeypatch.setattr(game_data_sync, "_build_catalog_snapshot", build_catalog)
    monkeypatch.setattr(game_data_sync, "_sync_catalog_images", sync_images)
    monkeypatch.setattr(game_data_sync, "_write_catalog_snapshot", write_catalog)
    monkeypatch.setattr(game_data_sync, "_build_patch_records", build_patch)
    monkeypatch.setattr(game_data_sync, "PATCH_OUTPUT_DIR", tmp_path / "patches")

    game_data_sync.main([])

    assert calls["session"] == (fake_client, 8)
    assert calls["latest_client"] is fake_session
    assert calls["catalog"] == (fake_session, "7.41f", 8)
    assert calls["images"] == (bundle, 8)
    assert calls["write"] is bundle
    assert calls["patch"] == (fake_session, "7.41f")
    assert (tmp_path / "patches" / "7_41f.json").is_file()
    assert game_data_sync.API_ROOT == API_ROOT
    assert game_data_sync.CATALOG_OUTPUT_DIR == API_ROOT / "app" / "data" / "catalog"
    assert default_patch_output == API_ROOT / "app" / "data" / "patches"
    assert game_data_sync.ALIASES_PATH == Path(game_data_sync.__file__).with_name(
        "hero_aliases_zh.yaml"
    )


@pytest.mark.parametrize("workers", ["0", "17"])
def test_invalid_workers_fail_before_constructing_client(
    workers: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_client() -> object:
        raise AssertionError("client was constructed for invalid arguments")

    monkeypatch.setattr(game_data_sync, "ValveDatafeedClient", unexpected_client)

    with pytest.raises(SystemExit) as exc_info:
        game_data_sync.main(["--workers", workers])

    assert exc_info.value.code == 2


def test_images_only_loads_committed_catalog_without_full_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = object()
    calls: list[tuple[str, object]] = []

    def unexpected_client() -> object:
        raise AssertionError("images-only must not create a Datafeed client")

    monkeypatch.setattr(game_data_sync, "ValveDatafeedClient", unexpected_client)
    monkeypatch.setattr(
        game_data_sync,
        "ValveFetchSession",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("images-only must not create a Datafeed session")
        ),
    )
    monkeypatch.setattr(
        game_data_sync,
        "_load_committed_catalog_bundle",
        lambda: calls.append(("load", bundle)) or bundle,
    )
    monkeypatch.setattr(
        game_data_sync,
        "_sync_catalog_images",
        lambda value, *, workers: calls.append(("images", (value, workers))) or 0,
    )
    monkeypatch.setattr(
        game_data_sync,
        "_build_catalog_snapshot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("images-only must not fetch a catalog")
        ),
    )

    game_data_sync.main(["--images-only", "--workers", "3"])

    assert calls == [("load", bundle), ("images", (bundle, 3))]


def test_moved_alias_resource_keeps_original_bytes() -> None:
    digest = hashlib.sha256(game_data_sync.ALIASES_PATH.read_bytes()).hexdigest()

    assert digest == "5d44314bf1c3ff9c13dd60453ad698c44f0888b145d9f04c43c8ebbc5aade022"


def test_legacy_script_is_a_thin_forwarding_entrypoint() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text(encoding="utf-8"))
    module_imports_main = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "app.integrations.valve.game_data_sync"
        and [alias.name for alias in node.names] == ["main"]
        for node in tree.body
    )
    business_definitions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]

    assert module_imports_main
    assert not business_definitions
