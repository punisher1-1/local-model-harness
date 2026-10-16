import yaml

from scripts.check_config import main


def write(tmp_path, profile):
    (tmp_path / "prompt.md").write_text("Server policy")
    path = tmp_path / "profiles.yaml"
    path.write_text(yaml.safe_dump({"profiles": {"local": {"backend_model": "m", "system_prompt_file": "prompt.md", **profile}}}))
    return str(path)


def test_valid_file_prints_a_summary(tmp_path, capsys):
    path = write(tmp_path, {"max_output_tokens": 4096, "backend_presets": {"m": {"thinking_budget_ratio": 0.25}}})
    assert main([path]) == 0
    out = capsys.readouterr().out
    assert "local: output 4096" in out and "m: ratio 0.25" in out and out.strip().endswith("Safe to run docker compose restart.")


def test_out_of_range_value_names_the_field(tmp_path, capsys):
    path = write(tmp_path, {"compaction": {"enabled": True, "timeout_seconds": 185}})
    assert main([path]) == 1
    assert "local.compaction.timeout_seconds" in capsys.readouterr().out


def test_yaml_and_missing_prompt_errors_are_reported(tmp_path, capsys):
    bad = tmp_path / "broken.yaml"
    bad.write_text("profiles:\n  local: [unclosed\n")
    assert main([str(bad)]) == 1
    path = write(tmp_path, {"system_prompt_file": "missing.md"})
    assert main([path]) == 1
    assert "missing.md" in capsys.readouterr().out
