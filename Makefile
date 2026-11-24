.DEFAULT_GOAL := help
SHELL := /bin/bash

UV ?= uv
RUN := $(UV) run
MANAGE := $(RUN) python manage.py
PORT ?= 8000
PLANTUML_IMAGE := plantuml/plantuml:1.2026.10
DOWNLOADS := .tmp/downloads
CENSUS_URL := https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer
GEONAMES_URL := https://download.geonames.org/export/dump/US.zip

.PHONY: help dev fmt lint type check test test-int test-postgres test-e2e test-all test-live \
        bench docs diagrams build clean data places run

help: ## List the targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  %-10s %s\n", $$1, $$2}'

dev: ## Install dependencies and the git hooks
	$(UV) sync
	$(RUN) pre-commit install

fmt: ## Format the code
	$(RUN) ruff format src tests manage.py
	$(RUN) ruff check --fix src tests manage.py

lint: ## Lint code, layering, security and Markdown
	$(RUN) ruff format --check src tests manage.py
	$(RUN) ruff check src tests manage.py
	$(RUN) lint-imports
	$(RUN) bandit -q -c pyproject.toml -r src
	npx --yes markdownlint-cli2@0.24.2

type: ## Type-check in strict mode
	$(RUN) mypy src tests manage.py

check: lint type ## Run every static check

test: ## Run the unit tests
	$(RUN) pytest tests/unit

test-int: ## Run the integration tests
	$(RUN) pytest tests/integration

test-postgres: ## Run unit and integration tests on PostgreSQL (needs Docker)
	FUELROUTE_TEST_POSTGRES=1 $(RUN) pytest tests/unit tests/integration

test-e2e: ## Run the end-to-end tests (real server and command line)
	$(RUN) pytest tests/e2e

test-all: ## Run every test level with branch coverage (95 percent minimum)
	$(RUN) coverage erase
	COVERAGE_PROCESS_START=pyproject.toml $(RUN) coverage run -m pytest
	$(RUN) coverage combine -q
	$(RUN) coverage report

test-live: ## Call the real OpenRouteService (needs ORS_API_KEY)
	FUELROUTE_LIVE_TESTS=1 $(RUN) pytest -m live tests/e2e

bench: ## Check the planning speed budget
	$(RUN) pytest tests/benchmarks --benchmark-enable --benchmark-columns=min,mean,max,rounds

docs: ## Lint the documentation
	npx --yes markdownlint-cli2@0.24.2

diagrams: ## Render every PlantUML source to SVG with the pinned image
	./scripts/render-diagrams.sh $(PLANTUML_IMAGE)

build: ## Build the wheel and source distribution
	$(UV) build

data: ## Create the database and import the committed station data
	mkdir -p var
	$(MANAGE) migrate --no-input
	$(MANAGE) import_stations

places: ## Download the public gazetteers and rebuild data/places.csv
	mkdir -p $(DOWNLOADS)
	curl -fsSL -o $(DOWNLOADS)/places.zip $(CENSUS_URL)/2025_Gaz_place_national.zip
	curl -fsSL -o $(DOWNLOADS)/cousubs.zip $(CENSUS_URL)/2025_Gaz_cousubs_national.zip
	curl -fsSL -o $(DOWNLOADS)/US.zip $(GEONAMES_URL)
	cd $(DOWNLOADS) && unzip -o -q places.zip && unzip -o -q cousubs.zip && unzip -o -q US.zip
	$(MANAGE) build_places \
	  --census-places $(DOWNLOADS)/2025_Gaz_place_national.txt \
	  --census-county-subdivisions $(DOWNLOADS)/2025_Gaz_cousubs_national.txt \
	  --geonames $(DOWNLOADS)/US.txt

run: ## Serve the API on PORT (default 8000) with the development server
	$(MANAGE) runserver $(PORT)

clean: ## Remove build output and tool caches
	rm -rf build dist .coverage .coverage.* htmlcov .pytest_cache .mypy_cache .ruff_cache \
	  .hypothesis .benchmarks .import_linter_cache
	find . -name __pycache__ -type d -prune -exec rm -rf {} +
