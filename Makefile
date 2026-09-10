# Convenience only. Every target is one command you can also type by hand, and
# CI runs the same commands rather than calling make — a Makefile that CI
# depends on becomes a place for CI-only behaviour to hide.
.PHONY: help install check lint type arch test cover build clean audit mutants

help:
	@grep -E '^[a-z-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-10s %s\n", $$1, $$2}'

install:  ## Editable install with the developer toolchain
	pip install -e ".[dev]"
	pre-commit install

check: lint type arch test  ## Everything CI checks on a pull request

lint:     ## ruff
	ruff check .

type:     ## mypy
	mypy

arch:     ## import-linter: the layering contracts
	lint-imports

test:     ## the test suite
	python3 -m pytest -q

cover:    ## tests with the branch-coverage floor
	coverage run -m pytest -q
	coverage combine || true
	coverage report

audit:    ## security scans
	bandit -q -c pyproject.toml -r iemod_fetch/
	pip-audit --strict || true

mutants:  ## mutation testing (slow; the nightly job runs this)
	mutmut run --paths-to-mutate iemod_fetch/

build:    ## the single-file zipapp
	python3 build.py

clean:
	rm -rf .pytest_cache .mypy_cache .ruff_cache .hypothesis .coverage* \
	       htmlcov build dist *.egg-info iemod-fetch.pyz
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
