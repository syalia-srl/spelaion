docs:
	uv run scriptorium render docs/scriptorium.yaml --only site

pdf:
	uv run scriptorium render docs/scriptorium.yaml --only print

docs-check: docs
	! grep -l 'Traceback (most recent call last)' docs/site/*.html
	! grep -l 'href="[0-9][0-9]-[a-z0-9-]*\.md' docs/site/*.html
	for h in $$(grep -oh 'href="[a-z0-9-]*\.html' docs/site/*.html | cut -d'"' -f2 | sort -u); do [ -f docs/site/$$h ] || { echo "broken link: $$h"; exit 1; }; done
	for c in docs/chapters/*.md; do uv run scriptorium tangle --test $$c -d docs || exit 1; done
	for e in docs/examples/*.py; do [ $$(basename $$e) = __init__.py ] || grep -q "export=$${e#docs/}" docs/chapters/*.md || { echo "$$e is not tangled from the docs"; exit 1; }; done
	for e in docs/examples/*.py; do uv run python $$e > /dev/null || exit 1; done
	uvx --from git+https://github.com/apiad/rift@v0.9.0 rift check .

.PHONY: docs pdf docs-check
