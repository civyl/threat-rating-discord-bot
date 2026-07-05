#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/civyl/threat-rating-discord-bot.git}"
APP_DIR="${APP_DIR:-/opt/threat-rating-discord-bot}"
SERVICE_NAME="threat-rating-discord-bot.service"

if [[ "${EUID}" -ne 0 ]]; then
  echo "Run this script with sudo."
  exit 1
fi

dnf install -y git python3 python3-pip

if [[ ! -d "${APP_DIR}/.git" ]]; then
  git clone "${REPO_URL}" "${APP_DIR}"
else
  git -C "${APP_DIR}" pull --ff-only
fi

chown -R opc:opc "${APP_DIR}"

sudo -u opc python3 -m venv "${APP_DIR}/.venv"
sudo -u opc "${APP_DIR}/.venv/bin/python" -m pip install --upgrade pip
sudo -u opc "${APP_DIR}/.venv/bin/python" -m pip install -r "${APP_DIR}/requirements.txt"

mkdir -p "${APP_DIR}/data"
chown -R opc:opc "${APP_DIR}/data"

if [[ ! -f "${APP_DIR}/.env" ]]; then
  cp "${APP_DIR}/.env.example" "${APP_DIR}/.env"
  chown opc:opc "${APP_DIR}/.env"
  chmod 600 "${APP_DIR}/.env"
  echo "Created ${APP_DIR}/.env. Edit it with your Discord token before starting the service."
fi

cp "${APP_DIR}/deploy/oracle/${SERVICE_NAME}" "/etc/systemd/system/${SERVICE_NAME}"
systemctl daemon-reload
systemctl enable "${SERVICE_NAME}"

echo "Setup complete."
echo "Next:"
echo "  sudo nano ${APP_DIR}/.env"
echo "  sudo systemctl start ${SERVICE_NAME}"
echo "  sudo systemctl status ${SERVICE_NAME}"
