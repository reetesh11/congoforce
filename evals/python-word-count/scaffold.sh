#!/usr/bin/env bash
# Seed the workspace with the Python fixture, a venv with pytest, and a bare remote.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cp -R "$here/../../fixtures/python-mini/." .
python3 -m venv .venv
.venv/bin/pip install -q pytest
git init -q -b main
git -c user.email=eval@example.com -c user.name=eval add -A
git -c user.email=eval@example.com -c user.name=eval commit -qm init
git init -q --bare -b main ../remote.git
git remote add origin ../remote.git
git push -q -u origin main
git remote set-head origin main
