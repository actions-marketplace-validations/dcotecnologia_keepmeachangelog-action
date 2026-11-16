# Keep Me A Changelog (action)

[![Tests](https://github.com/dcotecnologia/keepmeachangelog-action/actions/workflows/test.yml/badge.svg)](https://github.com/dcotecnologia/keepmeachangelog-action/actions/workflows/test.yml)
[![Coverage](https://raw.githubusercontent.com/dcotecnologia/keepmeachangelog-action/badges/coverage.svg)](https://github.com/dcotecnologia/keepmeachangelog-action/actions/workflows/test.yml)

GitHub Action that reads an entry from a `CHANGELOG.md` ([Keep a Changelog](https://keepachangelog.com/en/1.1.0/))
and validates it with [`keepmeachangelog-lint`](https://github.com/dcotecnologia/keepmeachangelog-lint).
It is a drop-in replacement for [`mindsers/changelog-reader-action`](https://github.com/mindsers/changelog-reader-action):
same inputs, same outputs, same config files. The built-in validation rules are replaced by the linter's.

## Usage

```yaml
- uses: actions/checkout@v7
- id: changelog
  uses: dcotecnologia/keepmeachangelog-action@v1
  with:
    version: ${{ steps.tag.outputs.version }}
    validation_level: error
- run: gh release create "$TAG" --notes-file "${{ steps.changelog.outputs.changes_file }}"
```

## Inputs

| Input | Default | Description |
| --- | --- | --- |
| `config_file` | — | Config file. Otherwise `.changelog-reader.json/.yml/.yaml`, `.changelogrc`, `.changelogrc.json` in the repo root |
| `path` | `./CHANGELOG.md` | Changelog file |
| `version` | latest released | Version wanted, or `Unreleased` |
| `validation_level` | `none` | `none`, `warn` (annotations only) or `error` (annotations and fail) |
| `validation_depth` | `10` | Newest released versions to validate |
| `version_scheme` | `semver` | `semver` or `pep440` (the linter validates semver only; with `pep440` validation is skipped with a warning) |
| `lint_config` | — | keepmeachangelog TOML config, passed to the linter (`title`, `sections`, `require-links`, …) |
| `lint_version` | latest | `keepmeachangelog` version installed from PyPI |
| `python_version` | `3.12` | Python used to run it (>= 3.11) |

Precedence: action input > config file > default. The config file takes `path`, `version`, `validation_level`,
`validation_depth` and `version_scheme`.

## Outputs

`version`, `date`, `status` (`prereleased`, `released`, `unreleased`, `yanked`), `changes`, `changes_file`.

## Validation

With `validation_level` `warn` or `error`, every problem found by the linter becomes an annotation on the file and line.
Besides the release rules from the reader action (valid SemVer, order, items per section, sections per release type) the
linter checks formatting: title, dates, section names, version links.

## License

[MIT](LICENSE)
