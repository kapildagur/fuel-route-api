# Contributing

Thank you for helping. This page explains how to set up the project, which checks a change must pass, and how to write commits and pull requests.

## Set up

You need [uv](https://docs.astral.sh/uv/), Node.js 20 or later for the Markdown linter, and Docker for the diagrams and for the tests that start Redis and PostgreSQL.

```bash
cp .env.example .env    # then set ORS_API_KEY
make dev                # installs dependencies and the pre-commit hooks
make data               # creates the database and imports the stations
make run                # serves http://127.0.0.1:8000
```

## Everyday commands

| Command | What it does |
| --- | --- |
| `make fmt` | Format the code and apply safe lint fixes. |
| `make lint` | Ruff, import-linter (layering), Bandit and markdownlint. |
| `make type` | mypy in strict mode over `src` and `tests`. |
| `make check` | `lint` and `type`. |
| `make test` | Unit tests. |
| `make test-int` | Integration tests: Django in process with a fake OpenRouteService. |
| `make test-postgres` | Unit and integration tests on PostgreSQL 18, started by Testcontainers; needs Docker. |
| `make test-e2e` | gunicorn and the management commands as subprocesses. |
| `make test-all` | Every level with branch coverage; fails below 95 percent. |
| `make test-live` | Two calls to the real OpenRouteService; needs `ORS_API_KEY`. |
| `make bench` | The NFR-01 speed budget. |
| `make diagrams` | Render `docs/diagrams/*.puml` to SVG with the pinned PlantUML image. |
| `make places` | Download the gazetteers and rebuild `data/places.csv`. |
| `make build` | Build the wheel and the source distribution. |
| `make clean` | Remove build output and caches. |

## Repository layout

| Path | Holds |
| --- | --- |
| `src/fuelroute/core` | Domain and use case, with no Django or HTTP imports. |
| `src/fuelroute/data` | Readers for the price file and the gazetteers. |
| `src/fuelroute/providers` | The OpenRouteService client. |
| `src/fuelroute/stations` | Django app: tables, import commands, database adapters. |
| `src/fuelroute/api` | Django app: views, serializers, errors, caching, wiring, map page. |
| `tests/unit`, `tests/integration`, `tests/e2e`, `tests/benchmarks` | Tests by level; the directory sets the marker. |
| `data` | The price file, the place list and the hand-checked aliases. |
| `docs` | Design, decision records and diagrams. |
| `postman` | The Postman collection and the Collection Runner data file. |

The layering is enforced: `import-linter` fails when a lower layer imports a higher one or when `core` imports Django.

## Making a change

1. Write a failing test that shows the behaviour, at the lowest level that can show it.
2. Change the code until it passes.
3. Update the requirement, the design, the test plan and the README if the behaviour changed, and add an entry under "Unreleased" in the changelog.
4. If you changed a `.puml` file, run `make diagrams` and commit the SVG with it. CI fails when they differ.
5. Run `make check` and `make test-all`.

## Commits and pull requests

- One change per pull request. The description says what changes and why, and names the requirement, issue or ADR it relates to.
- Commit subjects are short, in the imperative, and say what the change does: "Add a corridor width setting".
- ASCII only in commit messages.
- A change to a decision gets a new ADR that supersedes the old one; accepted records are not rewritten.
