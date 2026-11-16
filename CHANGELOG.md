# Changelog

All notable changes to this project will be documented in this file. The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.0.0] - 2026-11-16

### Added

- Add composite action that reads a changelog entry and validates it with `keepmeachangelog-lint`
- Add the same inputs and outputs as `mindsers/changelog-reader-action`, including config file and `changes_file`
- Add release workflow that creates the GitHub release from the changelog and moves the major tag
- Add coverage gate (100%) and coverage badge
- Add `lint_config`, `lint_version` and `python_version` inputs

[Unreleased]: https://github.com/dcotecnologia/keepmeachangelog-action/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/dcotecnologia/keepmeachangelog-action/releases/tag/v1.0.0
