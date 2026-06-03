#!/usr/bin/env bash
set -Eeuo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/release-npm-trusted.sh <version|patch|minor|major>

Examples:
  scripts/release-npm-trusted.sh 0.1.1
  scripts/release-npm-trusted.sh patch

This uses GitHub Actions trusted publishing for npm. It does not require local
npm login, OTP, browser confirmation, or an npm token.
EOF
}

if [[ $# -ne 1 || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

release_input="$1"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$repo_root"

for cmd in git npm gh node; do
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
done

if [[ -n "$(git status --porcelain)" ]]; then
  echo "Working tree is not clean. Commit or stash changes before release." >&2
  git status --short >&2
  exit 1
fi

current_version="$(node -p "require('./package.json').version")"
echo "Current version: $current_version"

npm version "$release_input" --no-git-tag-version
new_version="$(node -p "require('./package.json').version")"
tag="v$new_version"

echo "New version: $new_version"
echo "Running release checks..."
npm test
npm pack --dry-run

git add package.json
if [[ -f package-lock.json ]]; then
  git add package-lock.json
fi
git commit -m "Release npm $tag"
git tag "$tag"
git push origin HEAD --tags

echo "Triggering trusted npm publish workflow for $tag..."
gh workflow run npm-publish.yml --repo lachlanchen/aginti-browser --ref main

echo "Release workflow triggered. Watch it with:"
echo "  gh run list --repo lachlanchen/aginti-browser --workflow npm-publish.yml --limit 1"
echo "  gh run watch <run-id> --repo lachlanchen/aginti-browser --exit-status"
