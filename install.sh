#!/usr/bin/env bash
set -e

VENV_DIR=".venv"
REQ_FILE="requirements.txt"

echo "==> Vérification de python3..."
if ! command -v python3 >/dev/null 2>&1; then
  echo "Erreur : python3 introuvable. Installez Python 3."
  exit 1
fi

# Create venv if missing
if [ ! -d "$VENV_DIR" ]; then
  echo "==> Création du virtualenv dans ./$VENV_DIR ..."
  python3 -m venv "$VENV_DIR"
fi

# Activate venv for the rest of the script
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

echo "==> Mise à jour de pip..."
python -m pip install --upgrade pip setuptools wheel

if [ -f "$REQ_FILE" ]; then
  echo "==> Installation des dépendances depuis $REQ_FILE ..."
  pip install -r "$REQ_FILE"
else
  echo "Aucun $REQ_FILE trouvé à la racine. Créez-le puis relancez ce script."
  exit 1
fi

echo "==> Terminé. Pour utiliser le projet :"
echo "    source $VENV_DIR/bin/activate"
echo "    python yt-dlp_gui_fixed.py"
