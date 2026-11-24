#!/usr/bin/env bash
# Render every docs/diagrams/*.puml to SVG with a pinned PlantUML image.
# -nometadata keeps the source out of the SVG, so every machine writes the same bytes
# and CI can fail when a committed SVG differs from its source.
set -euo pipefail

image="${1:?usage: render-diagrams.sh <plantuml-image>}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

docker run --rm \
  --user "$(id -u):$(id -g)" \
  --volume "${root}/docs/diagrams:/data" \
  "${image}" -tsvg -nometadata -failfast2 '/data/*.puml'
