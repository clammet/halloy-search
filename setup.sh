#!/bin/sh
# Create the project venv with python3.14 and a convenience wrapper.
set -eu
cd "$(dirname "$0")"

python3.14 -m venv .venv
echo "venv created at .venv (python: $(.venv/bin/python --version))"
echo "usage: ./halloy-search <term> [-C 2] [-i] [-b '#channel']"
