#!/bin/bash
set -e

INSTALL_DIR="$HOME/.local/bin"
REPO_URL="https://raw.githubusercontent.com/dabasaai/github_menu/main/github_menu.py"
REPO_URL_COMPAT="https://raw.githubusercontent.com/dabasaai/github_menu/main/github_menu_compat.py"

echo "=== gm installer ==="
echo

# 0. Detect Python version — use compat version for < 3.7
PY_CMD="python3"
if ! command -v python3 &>/dev/null; then
    PY_CMD="python"
fi

PY_MINOR=$($PY_CMD -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo "0")
PY_MAJOR=$($PY_CMD -c 'import sys; print(sys.version_info.major)' 2>/dev/null || echo "0")

if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 7 ]); then
    USE_COMPAT=1
    echo "Detected Python $PY_MAJOR.$PY_MINOR (< 3.7) — installing compatibility version."
else
    USE_COMPAT=0
    echo "Detected Python $PY_MAJOR.$PY_MINOR — installing standard version."
fi
echo

# 1. Create ~/.local/bin if needed
if [ ! -d "$INSTALL_DIR" ]; then
    echo "Creating $INSTALL_DIR..."
    mkdir -p "$INSTALL_DIR"
fi

# 2. Check PATH
if [[ ":$PATH:" != *":$INSTALL_DIR:"* ]]; then
    echo "Adding $INSTALL_DIR to PATH..."
    SHELL_RC=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    fi
    if [ -n "$SHELL_RC" ]; then
        echo "export PATH=\"\$HOME/.local/bin:\$PATH\"" >> "$SHELL_RC"
        echo "  Added to $SHELL_RC (restart shell or run: source $SHELL_RC)"
    else
        echo "  WARNING: Add this to your shell config manually:"
        echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
    fi
fi

# 3. Download gm
if [ "$USE_COMPAT" -eq 1 ]; then
    echo "Downloading gm (compat version for Python < 3.7)..."
    curl -fsSL "$REPO_URL_COMPAT" -o "$INSTALL_DIR/gm"
else
    echo "Downloading gm..."
    curl -fsSL "$REPO_URL" -o "$INSTALL_DIR/gm"
fi
chmod +x "$INSTALL_DIR/gm"

# 4. Check gh CLI
if ! command -v gh &>/dev/null; then
    echo
    echo "gh CLI not found. Installing..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        brew install gh
    elif command -v apt &>/dev/null; then
        sudo apt install -y gh
    elif command -v dnf &>/dev/null; then
        sudo dnf install -y gh
    elif command -v yum &>/dev/null; then
        sudo yum install -y gh
    elif command -v pacman &>/dev/null; then
        sudo pacman -S --noconfirm github-cli
    else
        echo "  Could not auto-install gh. Please install manually: https://cli.github.com"
    fi
fi

# 5. Check gh auth
if command -v gh &>/dev/null; then
    if ! gh auth status &>/dev/null; then
        echo
        echo "gh CLI not logged in. Running 'gh auth login'..."
        gh auth login
    fi
fi

# 6. Add shell wrapper for auto cd
GM_FUNC='# gm wrapper — auto cd into cloned repo
gm() {
    local cd_file="$HOME/.cache/gm/last_clone_dir"
    rm -f "$cd_file"
    command gm "$@"
    if [ -f "$cd_file" ]; then
        local target
        target=$(cat "$cd_file")
        rm -f "$cd_file"
        if [ -n "$target" ] && [ -d "$target" ]; then
            cd "$target"
            echo "  cd $target"
        fi
    fi
}'

SHELL_RC=""
if [ -f "$HOME/.zshrc" ]; then
    SHELL_RC="$HOME/.zshrc"
elif [ -f "$HOME/.bashrc" ]; then
    SHELL_RC="$HOME/.bashrc"
fi

if [ -n "$SHELL_RC" ]; then
    if ! grep -q 'last_clone_dir' "$SHELL_RC"; then
        echo "" >> "$SHELL_RC"
        echo "$GM_FUNC" >> "$SHELL_RC"
        echo "  Added gm wrapper to $SHELL_RC"
    fi
fi

echo
echo "Done! Restart shell or run: source $SHELL_RC"
echo "Then run 'gm' to start."
