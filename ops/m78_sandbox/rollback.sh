#!/bin/sh
# Stops only this sandbox; leaves artifacts and evidence untouched.
set -eu
[ "$(id -u)" = 0 ]
systemctl stop intelligenceos-m78-sandbox.service
