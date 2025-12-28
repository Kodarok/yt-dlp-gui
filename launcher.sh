#!/usr/bin/env bash
set -e

VENV_DIR=".venv"
PY_SCRIPT="youtube-download-gui.py"

if [ ! -d "$VENV_DIR" ]; then
  echo "L'environnement virtuel n'existe pas. Exécutez ./install.sh d'abord."
  exit 1
fi

PYBIN="$VENV_DIR/bin/python"

if [ ! -x "$PYBIN" ]; then
  echo "Impossible de trouver l'interpréteur dans $PYBIN"
  exit 1
fi

echo "Activation via $PYBIN (pas de 'source' nécessaire)..."
exec "$PYBIN" "$PY_SCRIPT"
