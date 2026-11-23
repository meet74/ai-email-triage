PY := .venv/bin/python
PIP := .venv/bin/pip

.PHONY: setup test demo eval serve workflows e2e screenshots clean

setup:
	python3 -m venv .venv
	$(PIP) install -q -r requirements-dev.txt

test:
	$(PY) -m pytest -q
	node --test tests/js/code_nodes.test.mjs

demo:
	PYTHONWARNINGS=ignore $(PY) scripts/demo.py

eval:
	PYTHONWARNINGS=ignore $(PY) -m eval.run_eval

serve:
	$(PY) -m triage

workflows:
	$(PY) scripts/build_workflows.py

e2e:
	$(PY) scripts/run_e2e.py

screenshots:
	$(PY) scripts/render_slack_html.py
	node scripts/screenshots.js

clean:
	rm -rf .pytest_cache eval/results/*.json eval/results/*.md
