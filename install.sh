#!/bin/sh
# Installs in a private user-owned environment, then opens browser authorization.
set -eu
umask 077
HAT_INSTALL_DIR="${HAT_INSTALL_DIR:-$HOME/.local/share/home-agent-tools}"
HAT_BIN_DIR="${HAT_BIN_DIR:-$HOME/.local/bin}"
HAT_SOURCE_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd)
if [ ! -f "$HAT_SOURCE_DIR/pyproject.toml" ] || [ ! -d "$HAT_SOURCE_DIR/home_agent_tools" ]; then
  HAT_SOURCE_DIR=$(mktemp -d)
  trap 'rm -rf "$HAT_SOURCE_DIR"' EXIT
  git clone --quiet https://github.com/potseeslc/home-agent-tools.git "$HAT_SOURCE_DIR"
  git -C "$HAT_SOURCE_DIR" checkout --quiet "${HAT_REF:-codex/browser-agent-setup}"
fi
mkdir -p "$HAT_INSTALL_DIR" "$HAT_BIN_DIR"
if [ ! -x "$HAT_INSTALL_DIR/venv/bin/python" ]; then
  if command -v uv >/dev/null 2>&1; then
    uv venv --python 3.12 "$HAT_INSTALL_DIR/venv"
  else
    python3.12 -m venv "$HAT_INSTALL_DIR/venv"
  fi
fi
if command -v uv >/dev/null 2>&1; then
  uv pip install --python "$HAT_INSTALL_DIR/venv/bin/python" -r "$HAT_SOURCE_DIR/requirements.lock"
  uv pip install --python "$HAT_INSTALL_DIR/venv/bin/python" --no-deps "$HAT_SOURCE_DIR"
else
  "$HAT_INSTALL_DIR/venv/bin/python" -m pip install -r "$HAT_SOURCE_DIR/requirements.lock"
  "$HAT_INSTALL_DIR/venv/bin/python" -m pip install --no-deps "$HAT_SOURCE_DIR"
fi
if [ -e "$HAT_BIN_DIR/home-agent-tools" ] && [ ! -L "$HAT_BIN_DIR/home-agent-tools" ]; then
  echo "Refusing to overwrite an existing home-agent-tools executable." >&2
  exit 1
fi
ln -sfn "$HAT_INSTALL_DIR/venv/bin/home-agent-tools" "$HAT_BIN_DIR/home-agent-tools"
"$HAT_BIN_DIR/home-agent-tools" setup "$@"
