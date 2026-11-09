.PHONY: test e2e ui deb run clean lint

test:
	PYTHONPATH=. python3 -m unittest discover -s tests/unit -t .

e2e:
	PYTHONPATH=. python3 -u tests/e2e_smoke.py

ui:
	.venv/bin/python -u tests/ui_smoke.py

run:
	python3 app/main.py

deb:
	packaging/deb/build.sh

lint:
	ruff check app core daemon tests 2>/dev/null || true

clean:
	rm -rf dist build docs/screens/*.png
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
