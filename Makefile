# Chronic Disease Data Exchange Lab — synthetic data only.
PYTHON ?= python
N ?= 5000
SEED ?= 20250101

.PHONY: help install data network exchange measures pipeline test lint format site app serve simulate-small golden clean

help:
	@echo "make install   - install pinned dependencies (core + app)"
	@echo "make data      - generate the synthetic population (N=$(N), SEED=$(SEED)) -> data/raw, data/ground_truth"
	@echo "make network   - stand up simulated nodes in-process, health-check, publish directory"
	@echo "make exchange  - run Public Health bulk flow, Treatment query, refusals; dedup; examples/"
	@echo "make measures  - compute measures, pipeline effects, single-org vs network, data quality -> outputs/"
	@echo "make pipeline  - data + network + exchange + measures"
	@echo "make test      - ruff + pytest (FHIR validation, filtering, audit, dedup, measures)"
	@echo "make site      - build the static site into _site/"
	@echo "make app       - run the Streamlit app (offline, from committed outputs)"

install:
	$(PYTHON) -m pip install -r requirements-app.txt

data:
	$(PYTHON) -m synth.generate --n $(N) --seed $(SEED)

network:
	$(PYTHON) -m network.build

exchange:
	$(PYTHON) -m exchange.run

measures:
	$(PYTHON) -m measures.run
	$(PYTHON) -m app.demo_slice

pipeline: data network exchange measures

lint:
	ruff check .
	ruff format --check .

format:
	ruff format .
	ruff check --fix .

test: lint
	$(PYTHON) -m pytest

simulate-small:
	$(PYTHON) -m tests.simulate_small

golden:
	$(PYTHON) -m tests.simulate_small --write-golden

site:
	$(PYTHON) -m sitegen.build

app:
	streamlit run app/streamlit_app.py

serve:
	$(PYTHON) -m network.serve

clean:
	rm -rf data _site .pytest_cache .ruff_cache
