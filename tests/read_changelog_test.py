from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import read_changelog as rc

FIX = Path(__file__).parent.parent / ".github" / "fixtures"


@pytest.fixture
def out(tmp_path, monkeypatch):
    target = tmp_path / "output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(target))
    return target


def outputs(target: Path) -> dict[str, str]:
    result, name, delim, buf = {}, None, None, []
    for line in target.read_text().splitlines():
        if name is None:
            name, delim = line.split("<<")
            buf = []
        elif line == delim:
            result[name] = "\n".join(buf)
            name = None
        else:
            buf.append(line)
    return result


def go(tmp_path, **inputs):
    env = {f"INPUT_{k.upper()}": v for k, v in inputs.items()}
    env["RUNNER_TEMP"] = str(tmp_path)
    return rc.run(env, tmp_path)


def test_latest_released(tmp_path, out):
    assert go(tmp_path, path=str(FIX / "changelog-yanked.md")) == 0
    o = outputs(out)
    assert (o["version"], o["date"], o["status"]) == ("2.0.0", "2024-01-15", "yanked")
    assert Path(o["changes_file"]).read_text() == o["changes"]
    assert "Critical regression" in o["changes"]


@pytest.mark.parametrize(
    ("fixture", "version", "scheme", "expected", "status"),
    [
        ("changelog-unreleased.md", "Unreleased", "semver", "Unreleased", "unreleased"),
        ("changelog-unreleased.md", "1.0.0", "semver", "1.0.0", "released"),
        ("changelog-prereleased.md", None, "semver", "2.0.0-alpha.1", "prereleased"),
        ("changelog-pep440.md", None, "pep440", "0.1.0a1", "prereleased"),
        ("changelog-pep440.md", "0.0.1", "pep440", "0.0.1", "released"),
    ],
)
def test_entries(tmp_path, out, fixture, version, scheme, expected, status):
    inputs = {"path": str(FIX / fixture), "version_scheme": scheme}
    if version:
        inputs["version"] = version
    go(tmp_path, **inputs)
    o = outputs(out)
    assert (o["version"], o["status"]) == (expected, status)


def test_unreleased_has_no_date(tmp_path, out):
    go(tmp_path, path=str(FIX / "changelog-unreleased.md"), version="Unreleased")
    assert outputs(out)["date"] == ""


def test_unknown_version(tmp_path, out):
    with pytest.raises(rc.ChangelogError, match="No log entry found for version 9.9.9"):
        go(tmp_path, path=str(FIX / "changelog-yanked.md"), version="9.9.9")


def test_no_entries(tmp_path, out):
    p = tmp_path / "C.md"
    p.write_text("# Changelog\n")
    with pytest.raises(rc.ChangelogError, match="^No log entry found$"):
        go(tmp_path, path=str(p))


def test_missing_file(tmp_path, out):
    with pytest.raises(rc.ChangelogError, match="Cannot read"):
        go(tmp_path, path=str(tmp_path / "nope.md"))


def test_reference_links_resolved(tmp_path, out):
    p = tmp_path / "C.md"
    p.write_text(
        "# Changelog\r\n\r\n## [1.0.0] - 2024-01-01\r\n\r\n### Added\r\n\r\n"
        "- See [docs][] and [docs][] and [missing][]\r\n\r\n"
        "[docs]: https://example.com/docs\r\n[1.0.0]: https://example.com/r\r\n"
    )
    go(tmp_path, path=str(p))
    text = outputs(out)["changes"]
    assert text.endswith("\n[docs]: https://example.com/docs")
    assert text.count("[docs]: https") == 1


def test_config_file_json_and_input_precedence(tmp_path, out):
    cfg = tmp_path / ".changelogrc"
    cfg.write_text(
        json.dumps({"path": str(FIX / "changelog-yanked.md"), "version": "1.0.0"})
    )
    go(tmp_path)
    assert outputs(out)["version"] == "1.0.0"
    out.unlink()
    go(tmp_path, version="2.0.0")
    assert outputs(out)["version"] == "2.0.0"


def test_config_file_yaml_explicit(tmp_path, out):
    pytest.importorskip("yaml")
    cfg = tmp_path / "cfg.yml"
    cfg.write_text(f"path: {FIX / 'changelog-yanked.md'}\nversion: 1.0.0\n")
    go(tmp_path, config_file="cfg.yml")
    assert outputs(out)["version"] == "1.0.0"


def test_config_file_missing_warns(tmp_path, out, capsys):
    go(tmp_path, config_file="nope.yml", path=str(FIX / "changelog-yanked.md"))
    assert "::warning::Config file 'nope.yml' not found" in capsys.readouterr().out


def test_config_validation(tmp_path, capsys):
    cfg = rc.validate_config(
        {
            "path": 1,
            "version": 2,
            "validation_level": "x",
            "version_scheme": "y",
            "validation_depth": -1,
        },
        "f",
    )
    assert cfg == {}
    assert capsys.readouterr().out.count("::warning::") == 5
    assert rc.validate_config(None, "f") == {}
    assert rc.validate_config({"validation_depth": 3}, "f") == {"validation_depth": 3}
    with pytest.raises(rc.ChangelogError, match="got array"):
        rc.validate_config([], "f")
    with pytest.raises(rc.ChangelogError, match="got str"):
        rc.validate_config("x", "f")


def test_invalid_inputs_fall_back(tmp_path, out, capsys):
    go(
        tmp_path,
        path=str(FIX / "changelog-yanked.md"),
        validation_level="loud",
        version_scheme="calver",
        validation_depth="many",
    )
    text = capsys.readouterr().out
    assert "Invalid validation_level 'loud'" in text
    assert "Invalid version_scheme 'calver'" in text
    assert "Invalid validation_depth 'many'" in text
    assert "No target version specified" in text


def test_validation_none_skips(tmp_path, out, capsys):
    go(tmp_path, path=str(FIX / "changelog-yanked.md"))
    assert "Skipping validation" in capsys.readouterr().out


BAD = (
    "# Changelog\n\n## [1.0.0] - 2024-01-01\n\n### Added\n\n- ok\n\n"
    "## [1.0.1] - 2024-02-01\n\n### Fixed\n\n- wrong order\n\n"
    "[1.0.0]: https://github.com/o/r/releases/tag/v1.0.0\n"
    "[1.0.1]: https://github.com/o/r/releases/tag/v1.0.1\n"
)


def test_validation_warn_does_not_fail(tmp_path, out, capsys):
    p = tmp_path / "C.md"
    p.write_text(BAD)
    assert go(tmp_path, path=str(p), validation_level="warn") == 0
    assert "::warning file=" in capsys.readouterr().out
    assert outputs(out)["version"] == "1.0.0"


def test_validation_error_fails(tmp_path, out, capsys):
    p = tmp_path / "C.md"
    p.write_text(BAD)
    with pytest.raises(rc.ChangelogError, match="invalid"):
        go(tmp_path, path=str(p), validation_level="error")
    assert "::error file=" in capsys.readouterr().out
    assert not out.exists()


def test_validation_clean_changelog(tmp_path, out, capsys):
    p = tmp_path / "C.md"
    p.write_text(
        "# Changelog\n\n## [1.0.0] - 2024-01-01\n\n### Added\n\n- ok\n\n"
        "[1.0.0]: https://github.com/o/r/releases/tag/v1.0.0\n"
    )
    go(tmp_path, path=str(p), validation_level="error")
    assert "::error" not in capsys.readouterr().out


def test_validation_depth_limits_window(tmp_path, out):
    p = tmp_path / "C.md"
    p.write_text(BAD)
    go(tmp_path, path=str(p), validation_level="error", validation_depth="1")


def test_lint_config_passed(tmp_path, out):
    cfg = tmp_path / "lint.toml"
    cfg.write_text('title = "History"\n')
    with pytest.raises(rc.ChangelogError):
        go(
            tmp_path,
            path=str(FIX / "changelog-unreleased.md"),
            validation_level="error",
            lint_config=str(cfg),
        )


def test_lint_bad_config_is_hard_failure(tmp_path, out):
    cfg = tmp_path / "lint.toml"
    cfg.write_text("bogus = 1\n")
    with pytest.raises(rc.ChangelogError, match="invalid lint config"):
        go(
            tmp_path,
            path=str(FIX / "changelog-unreleased.md"),
            validation_level="warn",
            lint_config=str(cfg),
        )


def test_pep440_skips_validation(tmp_path, out, capsys):
    go(
        tmp_path,
        path=str(FIX / "changelog-pep440.md"),
        version_scheme="pep440",
        validation_level="error",
    )
    assert "only validates SemVer" in capsys.readouterr().out


def test_set_output_without_github_output(monkeypatch, capsys):
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    rc.set_output("a", "b")
    assert capsys.readouterr().out == "a=b\n"


def test_annotation_escaping(capsys):
    rc.error("100%\nnext", "a,b:c.md", 3)
    assert (
        capsys.readouterr().out == "::error file=a%2Cb%3Ac.md,line=3::100%25%0Anext\n"
    )


def test_version_schemes():
    assert rc.is_valid_version("v1.2.3", "semver")
    assert not rc.is_valid_version("1.2", "semver")
    assert rc.is_valid_version("1.0.dev1", "pep440")
    assert rc.is_prerelease("1.0.dev1", "pep440")
    assert not rc.is_prerelease("1.0.post1", "pep440")
    assert not rc.is_prerelease("nope", "semver")
    assert rc.is_prerelease("1.0.0-rc.1", "semver")


def test_config_valid_choices():
    cfg = rc.validate_config(
        {"validation_level": "warn", "version_scheme": "pep440"}, "f"
    )
    assert cfg == {"validation_level": "warn", "version_scheme": "pep440"}


def test_negative_depth_falls_back(tmp_path, out, capsys):
    go(tmp_path, path=str(FIX / "changelog-yanked.md"), validation_depth="-1")
    assert "Invalid validation_depth '-1'" in capsys.readouterr().out


def test_empty_chunk_is_ignored(tmp_path, out):
    p = tmp_path / "C.md"
    p.write_text("# Changelog\n## \n## [1.0.0] - 2024-01-01\n\n- x\n")
    go(tmp_path, path=str(p))
    assert outputs(out)["version"] == "1.0.0"
    assert rc._version_token("") is None
