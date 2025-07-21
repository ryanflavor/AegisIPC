#!/bin/bash
# Script to ensure pre-commit hooks are properly installed

set -euo pipefail

echo "🔧 Installing pre-commit hooks..."

# Check if uv is installed
if ! command -v uv &> /dev/null; then
    echo "❌ Error: uv is not installed. Please install uv first."
    echo "Run: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# Install pre-commit if not already installed
if ! uv run pre-commit --version &> /dev/null; then
    echo "📦 Installing pre-commit..."
    uv sync
fi

# Install the git hooks
echo "🪝 Installing git hooks..."
uv run pre-commit install
uv run pre-commit install --hook-type commit-msg
uv run pre-commit install --hook-type pre-push

# Run hooks on all files to verify installation
echo "✅ Running hooks on all files to verify installation..."
uv run pre-commit run --all-files || true

echo "✨ Pre-commit hooks installed successfully!"
echo ""
echo "The following hooks are now active:"
echo "  - pre-commit: Runs before each commit"
echo "  - commit-msg: Validates commit messages"
echo "  - pre-push: Runs before pushing to remote"
echo ""
echo "To manually run hooks: uv run pre-commit run --all-files"
