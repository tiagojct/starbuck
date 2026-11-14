#!/bin/sh
# Deploys the built site to the VPS at starbuck.tiagojacinto.eu, the same way as the Sub-Sub
# site and the other static sites there: each deploy is a new directory under releases/,
# named <n>-<commit>, and Caddy serves whatever the `current` symlink points to. Old
# releases stay, so going back means pointing `current` at an earlier one.
#
# The hostname, Caddy route, tunnel ingress and DNS record were set up once on the VPS
# with /opt/vps/bin/add-site starbuck.tiagojacinto.eu. See site/README.md.
set -eu

HOST=vps
DIR=/opt/vps/caddy/srv/starbuck.tiagojacinto.eu
cd "$(dirname "$0")/.."

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "Commit your changes first: the release is named after the commit." >&2
  exit 1
fi

npm run build
node scripts/check.mjs

SHA=$(git rev-parse --short HEAD)
# The next number is one more than the highest number in use, so deleting old
# releases never makes a number repeat.
N=$(ssh "$HOST" "mkdir -p $DIR/releases && ls $DIR/releases" | sed -n 's/^\([0-9][0-9]*\)-.*/\1/p' | sort -n | tail -1)
REL="$((${N:-0} + 1))-$SHA"

rsync -az --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r _site/ "$HOST:$DIR/releases/$REL/"
ssh "$HOST" "cd $DIR && ln -sfn releases/$REL current && echo \"current -> \$(readlink current)\""
