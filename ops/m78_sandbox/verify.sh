#!/bin/sh
set -eu
exec /usr/bin/python3 "$(dirname "$0")/launch.py" verify
