#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -f .env ]; then
  cp .env.example .env
  echo ".env criado a partir de .env.example"
else
  echo ".env ja existe"
fi
