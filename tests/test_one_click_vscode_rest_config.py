import json
from pathlib import Path

from scripts.one_click import load_vscode_worker_specs, parse_vscode_rest_map


def test_parse_vscode_rest_map():
    raw = "codex=http://127.0.0.1:49818,codex2=http://127.0.0.1:49819"
    out = parse_vscode_rest_map(raw)
    assert out["codex"] == "http://127.0.0.1:49818"
    assert out["codex2"] == "http://127.0.0.1:49819"


def test_load_vscode_worker_specs_from_config_file(tmp_path: Path):
    config = {
        "workers": [
            {"target": "codex", "port": 9003, "rest_url": "http://127.0.0.1:49818"},
            {"target": "codex2", "port": 9013, "rest_url": "http://127.0.0.1:49819"},
        ]
    }
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(json.dumps(config), encoding="utf-8")

    specs = load_vscode_worker_specs(
        repo_root=tmp_path,
        default_rest_url="http://127.0.0.1:49818",
        default_routing={"codex": 9003},
        config_rel_path="cfg.json",
        raw_rest_map="",
    )
    assert len(specs) == 2
    assert specs[0]["target"] == "codex"
    assert specs[1]["target"] == "codex2"
    assert specs[1]["port"] == 9013


def test_load_vscode_worker_specs_supports_cli_override(tmp_path: Path):
    cfg_path = tmp_path / "cfg.json"
    cfg_path.write_text(
        json.dumps({"workers": [{"target": "codex", "port": 9003, "rest_url": "http://127.0.0.1:49818"}]}),
        encoding="utf-8",
    )
    specs = load_vscode_worker_specs(
        repo_root=tmp_path,
        default_rest_url="http://127.0.0.1:49818",
        default_routing={"codex": 9003},
        config_rel_path="cfg.json",
        raw_rest_map="codex=http://127.0.0.1:59999,codex2=http://127.0.0.1:60000",
    )

    by_target = {item["target"]: item for item in specs}
    assert by_target["codex"]["rest_url"] == "http://127.0.0.1:59999"
    assert by_target["codex"]["port"] == 9003
    assert by_target["codex2"]["rest_url"] == "http://127.0.0.1:60000"
