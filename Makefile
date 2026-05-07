# tg-cli developer gate

PYTEST = .venv/bin/pytest
PYTHON = .venv/bin/python

.PHONY: gate test diff-check install-hooks help

help:
	@echo "Targets:"
	@echo "  gate           Run test + diff-check (use before pushing)"
	@echo "  test           Run pytest"
	@echo "  diff-check     git diff --check (whitespace + conflict markers)"
	@echo "  install-hooks  Install commit-msg hook for Conventional Commits"

gate: test diff-check
	@echo "PASS: gate clean"

test:
	$(PYTEST) tests/tgcli -q

diff-check:
	@git diff --check

install-hooks:
	@cp .githooks/commit-msg .git/hooks/commit-msg
	@chmod +x .git/hooks/commit-msg
	@echo "commit-msg hook installed"
