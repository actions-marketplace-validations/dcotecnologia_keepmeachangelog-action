"""Read a Keep a Changelog file and validate it with keepmeachangelog-lint.

Drop-in equivalent of mindsers/changelog-reader-action: same inputs, same
outputs, same entry parsing. The validation engine is `keepmeachangelog`
(https://github.com/dcotecnologia/keepmeachangelog-lint) instead of the
action's built-in rules.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from keepmeachangelog.cli import load_config
from keepmeachangelog.linter import SEMVER_RE, Config, lint

CONFIG_FILE_NAMES = (
    ".changelog-reader.json",
    ".changelog-reader.yml",
    ".changelog-reader.yaml",
    ".changelogrc",
    ".changelogrc.json",
)
VALIDATION_LEVELS = ("none", "warn", "error")
DEFAULT_VALIDATION_LEVEL = "error"
VERSION_SCHEMES = ("semver", "pep440")
DEFAULT_PATH = "./CHANGELOG.md"
DEFAULT_VALIDATION_DEPTH = 10

PEP440_RE = re.compile(
    r"^v?(?:[0-9]+!)?[0-9]+(?:\.[0-9]+)*"
    r"(?P<pre>[-_.]?(?:alpha|a|beta|b|preview|pre|c|rc)[-_.]?[0-9]*)?"
    r"(?:-[0-9]+|[-_.]?(?:post|rev|r)[-_.]?[0-9]*)?"
    r"(?P<dev>[-_.]?dev[-_.]?[0-9]*)?"
    r"(?:\+[a-z0-9]+(?:[-_.][a-z0-9]+)*)?$",
    re.IGNORECASE,
)
LINK_DEFINITION_RE = re.compile(r"^\[(.+?)\]:\s*https?://\S+\s*$")
LINK_LINE_RE = re.compile(r"^\[.*\]:\s*http")
PLACEHOLDER_RE = re.compile(r"\[(.+?)\]\[\]", re.IGNORECASE)


class ChangelogError(Exception):
    """A failure that must fail the action with a plain message."""


@dataclass(frozen=True)
class Entry:
    id: str
    date: str | None
    status: str
    text: str


# --------------------------------------------------------------------------
# workflow commands
# --------------------------------------------------------------------------


def _escape_data(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _escape_property(value: str) -> str:
    return _escape_data(value).replace(":", "%3A").replace(",", "%2C")


def warning(message: str, file: str | None = None, line: int | None = None) -> None:
    _annotate("warning", message, file, line)


def error(message: str, file: str | None = None, line: int | None = None) -> None:
    _annotate("error", message, file, line)


def _annotate(kind: str, message: str, file: str | None, line: int | None) -> None:
    props = []
    if file:
        props.append(f"file={_escape_property(file)}")
    if line:
        props.append(f"line={line}")
    head = f"::{kind} {','.join(props)}" if props else f"::{kind}"
    print(f"{head}::{_escape_data(message)}", flush=True)


def info(message: str) -> None:
    print(message, flush=True)


def set_output(name: str, value: str) -> None:
    target = os.environ.get("GITHUB_OUTPUT")
    if not target:
        print(f"{name}={value}")
        return
    delimiter = f"ghadelim_{uuid.uuid4().hex}"
    with open(target, "a", encoding="utf-8") as fh:
        fh.write(f"{name}<<{delimiter}\n{value}\n{delimiter}\n")


# --------------------------------------------------------------------------
# configuration (same keys and precedence as changelog-reader-action)
# --------------------------------------------------------------------------


def _load_file(path: Path) -> Any:
    content = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yml", ".yaml"):
        import yaml  # installed next to keepmeachangelog by action.yml

        return yaml.safe_load(content)
    return json.loads(content)


def validate_config(value: Any, source: str) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        kind = "array" if isinstance(value, list) else type(value).__name__
        raise ChangelogError(
            f"Config file {source} must contain an object at the root, got {kind}."
        )
    config: dict[str, Any] = {}
    for key in ("path", "version"):
        if key in value:
            if isinstance(value[key], str):
                config[key] = value[key]
            else:
                warning(f"Config '{source}': '{key}' must be a string. Ignoring.")
    for key, allowed in (
        ("validation_level", VALIDATION_LEVELS),
        ("version_scheme", VERSION_SCHEMES),
    ):
        if key in value:
            if value[key] in allowed:
                config[key] = value[key]
            else:
                warning(
                    f"Config '{source}': '{key}' must be one of "
                    f"{', '.join(allowed)}. Ignoring."
                )
    if "validation_depth" in value:
        depth = value["validation_depth"]
        if isinstance(depth, int) and not isinstance(depth, bool) and depth >= 0:
            config["validation_depth"] = depth
        else:
            warning(
                f"Config '{source}': 'validation_depth' must be a non-negative "
                "integer. Ignoring."
            )
    return config


def get_config(config_path: str | None, cwd: Path) -> tuple[dict[str, Any], str | None]:
    """Return (config, missing explicit path)."""
    if config_path:
        resolved = (cwd / config_path).resolve()
        if not resolved.exists():
            return {}, config_path
        return validate_config(_load_file(resolved), str(resolved)), None
    for name in CONFIG_FILE_NAMES:
        candidate = cwd / name
        if candidate.exists():
            return validate_config(_load_file(candidate), str(candidate)), None
    return {}, None


# --------------------------------------------------------------------------
# version schemes
# --------------------------------------------------------------------------


def is_valid_version(raw: str, scheme: str) -> bool:
    if scheme == "semver":
        return SEMVER_RE.match(raw.lstrip("v=")) is not None
    return PEP440_RE.match(raw) is not None


def is_prerelease(raw: str, scheme: str) -> bool:
    if scheme == "semver":
        m = SEMVER_RE.match(raw.lstrip("v="))
        return m is not None and m.group(4) is not None
    m = PEP440_RE.match(raw)
    return m is not None and (m["pre"] is not None or m["dev"] is not None)


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------


def _version_token(chunk: str) -> str | None:
    if m := re.match(r"^\[([^\]]+)\]", chunk):
        return m[1]
    if m := re.match(r"^(\S+)", chunk):
        return m[1]
    return None


def get_entries(raw: str, scheme: str) -> list[str]:
    chunks = []
    for chunk in raw.split("\n## "):
        token = _version_token(chunk)
        if token is None:
            continue
        if token.lower() == "unreleased" or is_valid_version(token, scheme):
            chunks.append(chunk)
    return chunks


def _status(version: str, title: str, scheme: str) -> str:
    if is_prerelease(version, scheme):
        return "prereleased"
    if re.search(r"\[yanked\]", title, re.IGNORECASE):
        return "yanked"
    if re.search(r"\bunreleased\b", title, re.IGNORECASE):
        return "unreleased"
    return "released"


def parse_entry(chunk: str, scheme: str, registry: dict[str, str]) -> Entry:
    title, *other = chunk.strip().split("\n")
    version_part, _, date_part = title.partition(" - ")
    m = re.search(r"[a-zA-Z0-9.\-+]+", version_part)
    version = m[0] if m else ""
    date = None
    if date_part:
        dm = re.search(r"[0-9-]+", date_part)
        date = dm[0] if dm else None
    body = "\n".join(line for line in other if not LINK_LINE_RE.match(line))
    refs: list[str] = []
    for ref in PLACEHOLDER_RE.finditer(body):
        name = ref[1].lower()
        if name not in refs:
            refs.append(name)
    resolved = [registry[r] for r in refs if r in registry]
    text = f"{body}\n" + "\n".join(resolved) if resolved else body
    return Entry(version, date, _status(version, title, scheme), text)


def build_registry(raw: str) -> dict[str, str]:
    registry: dict[str, str] = {}
    for line in raw.strip().split("\n"):
        if m := LINK_DEFINITION_RE.match(line):
            registry[m[1].lower()] = line
    return registry


def read_entries(raw: str, scheme: str) -> list[Entry]:
    raw = raw.replace("\r\n", "\n")
    registry = build_registry(raw)
    return [parse_entry(c, scheme, registry) for c in get_entries(raw, scheme)]


def find_entry(entries: list[Entry], version: str | None) -> Entry:
    if version is not None:
        found = next((e for e in entries if e.id == version), None)
    else:
        found = next((e for e in entries if e.id.lower() != "unreleased"), None)
    if found is None:
        suffix = f" for version {version}" if version is not None else ""
        raise ChangelogError(f"No log entry found{suffix}")
    return found


# --------------------------------------------------------------------------
# validation through keepmeachangelog-lint
# --------------------------------------------------------------------------


def run_lint(
    path: str, text: str, depth: int, lint_config: str | None, level: str
) -> int:
    """Lint with keepmeachangelog, report each problem; return the count."""
    try:
        config = load_config(Path(lint_config)) if lint_config else None
    except (OSError, ValueError, KeyError) as e:
        raise ChangelogError(f"{lint_config}: invalid lint config: {e!r}") from e
    kwargs = {"validation_depth": depth}
    config = replace(config, **kwargs) if config else replace(Config(), **kwargs)
    emit = error if level == "error" else warning
    problems = lint(text, config)
    for prob in problems:
        emit(prob.message, path, prob.line)
    return len(problems)


# --------------------------------------------------------------------------
# entry point
# --------------------------------------------------------------------------


def _choice(name: str, raw: str, allowed: tuple[str, ...], default: str) -> str:
    if raw in allowed:
        return raw
    warning(
        f"Invalid {name} '{raw}'. Expected one of: {', '.join(allowed)}. "
        f"Falling back to '{default}'."
    )
    return default


def run(env: dict[str, str], cwd: Path) -> int:
    config, missing = get_config(env.get("INPUT_CONFIG_FILE") or None, cwd)
    if missing is not None:
        warning(f"Config file '{missing}' not found. Falling back to action inputs.")
    if config:
        info("Configuration loaded from file")

    path = env.get("INPUT_PATH") or config.get("path") or DEFAULT_PATH
    version = env.get("INPUT_VERSION") or config.get("version") or None
    level = _choice(
        "validation_level",
        env.get("INPUT_VALIDATION_LEVEL") or config.get("validation_level")
        or DEFAULT_VALIDATION_LEVEL,
        VALIDATION_LEVELS,
        DEFAULT_VALIDATION_LEVEL,
    )
    scheme = _choice(
        "version_scheme",
        env.get("INPUT_VERSION_SCHEME") or config.get("version_scheme") or "semver",
        VERSION_SCHEMES,
        "semver",
    )
    raw_depth = env.get("INPUT_VALIDATION_DEPTH") or str(
        config.get("validation_depth", DEFAULT_VALIDATION_DEPTH)
    )
    try:
        depth = int(raw_depth)
        if depth < 0:
            raise ValueError
    except ValueError:
        warning(
            f"Invalid validation_depth '{raw_depth}'. "
            f"Falling back to {DEFAULT_VALIDATION_DEPTH}."
        )
        depth = DEFAULT_VALIDATION_DEPTH

    if version is None:
        warning(
            "No target version specified. Will try to return the most recent "
            "one in the changelog file."
        )

    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as e:
        raise ChangelogError(f"Cannot read '{path}': {e.strerror or e}") from e

    problems = 0
    if level == "none":
        info("Validation level set to 'none'. Skipping validation.")
    elif scheme != "semver":
        warning(
            f"keepmeachangelog-lint only validates SemVer changelogs; skipping "
            f"validation for version_scheme '{scheme}'."
        )
    else:
        problems = run_lint(
            path, raw, depth, env.get("INPUT_LINT_CONFIG") or None, level
        )

    entry = find_entry(read_entries(raw, scheme), version)
    if problems and level == "error":
        raise ChangelogError(
            f"{entry.id} entry is invalid: {problems} problem(s) found in {path}."
        )

    set_output("version", entry.id)
    set_output("date", entry.date or "")
    set_output("status", entry.status)
    set_output("changes", entry.text)
    base = env.get("RUNNER_TEMP") or tempfile.gettempdir()
    out_dir = Path(tempfile.mkdtemp(prefix="changelog-reader-", dir=base))
    changes_file = out_dir / "changelog-entry.md"
    changes_file.write_text(entry.text, encoding="utf-8")
    set_output("changes_file", str(changes_file))
    return 0


def main() -> int:  # pragma: no cover - thin wrapper
    try:
        return run(dict(os.environ), Path.cwd())
    except ChangelogError as e:
        error(str(e))
        return 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
