#!/usr/bin/env bash
set -euo pipefail

IMAGE="dkr.cidrs.net/noblog"
VERSION_FILE="relaseversion.txt"

# ── Defaults ─────────────────────────────────────────────────────────────────
DO_BUILD=false
DO_PUSH=false
DO_TAG=false
VERSION=""

# ── Parse arguments ──────────────────────────────────────────────────────────
usage() {
  cat <<EOF
Usage: ./release.sh [flags]

Flags:
  --build             Build the Docker image
  --push              Push the image to the registry
  --tag               Git-tag the current commit with the version
  --version <ver>     Version string (used as Docker tag and baked into image)
                      If omitted, defaults to "latest-dev"

Examples:
  ./release.sh --build
      Build with tag "latest-dev"

  ./release.sh --build --version 1.2.0
      Build with tag "1.2.0"

  ./release.sh --build --push --version 1.2.0
      Build, tag, and push "1.2.0" + "latest"

  ./release.sh --push --tag --version 1.2.0
      Push "1.2.0" and git-tag the commit

  ./release.sh --build --push --tag --version 1.2.0
      Full release: build, push, git-tag
EOF
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --build)   DO_BUILD=true; shift ;;
    --push)    DO_PUSH=true; shift ;;
    --tag)     DO_TAG=true; shift ;;
    --version) VERSION="$2"; shift 2 ;;
    -h|--help) usage ;;
    *) echo "Unknown flag: $1"; usage ;;
  esac
done

# At least one action required
if ! $DO_BUILD && ! $DO_PUSH && ! $DO_TAG; then
  echo "Error: provide at least one of --build, --push, or --tag"
  echo ""
  usage
fi

# Default version
if [[ -z "$VERSION" ]]; then
  VERSION="latest-dev"
fi

echo "Version: $VERSION"
echo "$VERSION" > "$VERSION_FILE"

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

# ── Git tag ──────────────────────────────────────────────────────────────────
if $DO_TAG; then
  echo ""
  echo "Tagging git commit as v$VERSION ..."
  git tag -a "v$VERSION" -m "Release $VERSION"
  git push origin "v$VERSION"
  echo "✓ Tagged v$VERSION"
fi

echo ""
echo "Done."
