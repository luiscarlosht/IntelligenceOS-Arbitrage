#!/bin/sh
# Unsafe split preparation has been retired; use the verified installer.
set -eu
echo "Use install.py --manifest APPROVED_RECORD --bundle APPROVED_BUNDLE (read-only by default)." >&2
exit 1
