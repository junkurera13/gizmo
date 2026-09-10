#!/usr/bin/env bash
# Idempotent Cloud Agent bootstrap for the Gizmo repo.
# System packages here are additive to Cursor's default image; the Python brain
# and the web site are installed from their pinned manifests.
set -euo pipefail

cd "$(dirname "$0")/.."

# System dependencies. python3.12-venv is required to create the brain venv;
# ffmpeg backs Show media processing; build tooling covers any sdist fallback.
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3.12-venv python3-dev build-essential ffmpeg git curl

# Python brain (friend/gizmo_friend), installed editable from pyproject.toml.
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install --upgrade pip
pip install -e .

# Public web site (Next.js) from its lockfile.
cd web
npm ci
