#!/usr/bin/env bash
# Seed an eval workspace with a fixture repo, its dependencies and a bare remote.
# Usage: scaffold.sh python-mini|js-mini
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
fixture="$1"
cp -R "$here/../../fixtures/$fixture/." .
case "$fixture" in
  python-mini)
    python3 -m venv .venv
    .venv/bin/pip install -q pytest
    ;;
  js-mini)
    npm install --silent --no-audit --no-fund
    ;;
esac
git init -q -b main
git config user.email eval@example.com
git config user.name eval
git add -A
git commit -qm init
git init -q --bare -b main ../remote.git
git remote add origin ../remote.git
git push -q -u origin main
git remote set-head origin main
