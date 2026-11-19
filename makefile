.PHONY: help test typecheck modtest version version-patch version-minor version-major _bump-version
.SILENT:

# Pinned, so a mypy release never fails a commit the code did not change.
MYPY = uvx --quiet --from mypy==1.18.2 mypy
# The WebFetch mod's tests run under Claude Code's own runner, pinned the same way.
CLAUDE_CODE = npx --yes @anthropic-ai/claude-code@2.1.327

help: ## | List all available commands
	echo "Available commands in this makefile"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	| sed -n 's/^\(.*\): \(.*\)##\(.*\)/\1\3/p' \
	| column -t -s '|'

test: ## | Check the panoply-lib copies and the types, then run tests/, the install smoke check and the mod's tests
	../panoply-lib/sync.sh --check grille
	$(MYPY)
	python3 -m unittest discover -s tests -t .
	python3 src/grille/grille.py selftest
	$(CLAUDE_CODE) plugin test src/grille/claude-mod

typecheck: ## | Type-check src/grille as Python 3.9 reads it ([tool.mypy] in pyproject.toml)
	$(MYPY)

modtest: ## | Run the WebFetch mod's tests (src/grille/claude-mod/hooks/register.test.ts)
	$(CLAUDE_CODE) plugin test src/grille/claude-mod

version-patch: ## | Release the next PATCH version: stamp, test, tag, push, move the formula
	@$(MAKE) _bump-version BUMP=patch

version-minor: ## | Release the next MINOR version: stamp, test, tag, push, move the formula
	@$(MAKE) _bump-version BUMP=minor

version-major: ## | Release the next MAJOR version: stamp, test, tag, push, move the formula
	@$(MAKE) _bump-version BUMP=major

version: version-patch ## | Alias for version-patch (the common release)

# `__version__` in grille.py is the one home (pyproject.toml reads it at build time),
# so the next version is computed from it and handed to scripts/release.sh, which
# owns every step after that and refuses a dirty tree or an existing tag.
_bump-version:
	@NEXT=$$(python3 -c "import re,sys; \
		v=re.search(r'^__version__ = \"(\d+)\.(\d+)\.(\d+)\"', open('src/grille/grille.py').read(), re.M); \
		M,m,p=map(int,v.groups()); \
		print({'major':f'{M+1}.0.0','minor':f'{M}.{m+1}.0','patch':f'{M}.{m}.{p+1}'}['$(BUMP)'])") && \
		echo "--- Releasing $$NEXT ($(BUMP)) ---" && \
		scripts/release.sh "$$NEXT"
