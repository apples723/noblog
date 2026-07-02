#!/usr/bin/env bash
set -euo pipefail

IMAGE="dkr.cidrs.net/noblog"
VERSION_FILE="relaseversion.txt"

# ── Defaults ─────────────────────────────────────────────────────────────────
DO_BUILD=false
DO_PUSH=false
DO_RELEASE=false
VERSION=""

# ── Parse arguments ──────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: ./release.sh [flags]

Flags:
  --build             Build the Docker image
  --push              Push the image to the registry
  --release           Official release: updates version file and git-tags the commit
                      Requires --version/--tag in vX.Y.Z format
  --version <ver>     Version string (used as Docker tag and baked into image)
  --tag <ver>         Alias for --version
                      If omitted, defaults to "latest-dev"

Examples:
  ./release.sh --build
      Build with tag "latest-dev"

  ./release.sh --build --version 1.2.0
      Build with tag "1.2.0" (no version file update)

  ./release.sh --build --push --tag 1.2.0
      Build and push "1.2.0" + "latest" (no version file update)

  ./release.sh --build --push --release --version 1.2.0
      Full release: build, push, update version file, git-tag
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)           DO_BUILD=true; shift ;;
    --push)            DO_PUSH=true; shift ;;
    --release)         DO_RELEASE=true; shift ;;
    --version|--tag)   VERSION="$2"; shift 2 ;;
    -h|--help)         usage ;;
    *) echo "Unknown flag: $1"; usage ;;
  esac
done

# At least one action required
if ! $DO_BUILD && ! $DO_PUSH && ! $DO_RELEASE; then
  echo "Error: provide at least one of --build, --push, or --release"
  echo ""
  usage
fi

# Default version
if [[ -z "$VERSION" ]]; then
  VERSION="latest-dev"
fi

# Validate version format when releasing
if $DO_RELEASE; then
  if [[ -z "$VERSION" || "$VERSION" == "latest-dev" ]]; then
    echo "Error: --release requires an explicit version (--version or --tag)"
    exit 1
  fi
  if ! [[ "$VERSION" =~ ^v?[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    echo "Error: --release requires version in vX.Y.Z format (got: $VERSION)"
    exit 1
  fi
fi

echo "Version: $VERSION"

# ── Build ────────────────────────────────────────────────────────────────────
if $DO_BUILD; then
  echo ""
  echo "Building $IMAGE:$VERSION (linux/amd64) ..."
  docker build --platform linux/amd64 --build-arg APP_VERSION="$VERSION" -t "$IMAGE:$VERSION" -t "$IMAGE:latest" .
  echo "✓ Built $IMAGE:$VERSION"
fi

# ── Push ─────────────────────────────────────────────────────────────────────
if $DO_PUSH; then
  echo ""
  echo "Pushing $IMAGE:$VERSION ..."
  docker push "$IMAGE:$VERSION"
  docker push "$IMAGE:latest"
  echo "✓ Pushed $IMAGE:$VERSION"
fi

# ── Release (version file + git tag) ────────────────────────────────────────
if $DO_RELEASE; then
  echo ""
  echo "$VERSION" > "$VERSION_FILE"
  echo "✓ Updated $VERSION_FILE → $VERSION"

  # Ensure version has v prefix for git tag
  GIT_TAG="$VERSION"
  if [[ "$GIT_TAG" != v* ]]; then
    GIT_TAG="v$VERSION"
  fi

  echo "Tagging git commit as $GIT_TAG ..."
  git tag -a "$GIT_TAG" -m "Release $VERSION"
  git push origin "$GIT_TAG"
  echo "✓ Tagged $GIT_TAG"
fi

echo ""
echo "Done."
