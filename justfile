set windows-shell := ["powershell.exe", "-NoLogo", "-Command"]

[doc("All command information")]
help:
    @just --list --unsorted

alias l := lint
[doc("Check and format code with autofix (in pyproject.toml src/ tests/) using ruff")]
[group("dev")]
lint:
    uv run ruff format .
    uv run ruff check . --fix
    uv run ruff format .

alias tc := typecheck
[doc("Check types (in src/ and tests/) using ty")]
[group("dev")]
typecheck:
    uv run ty check

alias t := test
[doc("Run tests (in tests/) using pytest")]
[group("dev")]
test:
    uv run pytest -v -s

alias c := check
[doc("Run all checks (lint, typecheck, test)")]
[group("dev")]
check:
    just lint
    just typecheck
    just test
