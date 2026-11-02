#!/bin/sh
# Run ONLY with explicit deployment approval. Never stages production evidence.
set -eu
[ "$(id -u)" = 0 ]
base=/mnt/intelligenceos_data/arbitrage/sandbox/m78
mountpoint -q /mnt/intelligenceos_data
getent passwd intelligenceos-m78 >/dev/null
# Refuse to overwrite an existing sandbox, including symlinks.
[ ! -e "$base" ] && [ ! -L "$base" ]
install -d -o root -g root -m 0755 "$base"
install -d -o root -g root -m 0755 "$base/root" "$base/code" "$base/deps" "$base/evidence"
install -d -o intelligenceos-m78 -g intelligenceos-m78 -m 0700 "$base/output"
install -o root -g root -m 0444 "$(dirname "$0")/probe.py" "$base/probe.py"
echo 'Prepared empty layout only. Stage reviewed code, dependencies and synthetic fixtures separately; then verify.'
