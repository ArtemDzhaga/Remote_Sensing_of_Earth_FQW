#!/usr/bin/env bash
set -euo pipefail

# Configure Earthdata credentials in ~/.netrc without echoing the password.
# The resulting file is readable only by the current user.

read -r -p "Earthdata username: " EARTHDATA_USERNAME
read -r -s -p "Earthdata password: " EARTHDATA_PASSWORD
printf '\n'

NETRC_PATH="${HOME}/.netrc"
TMP_PATH="$(mktemp)"

if [[ -f "$NETRC_PATH" ]]; then
  awk '
    $1 == "machine" && $2 == "urs.earthdata.nasa.gov" {skip=1; next}
    $1 == "machine" {skip=0}
    !skip {print}
  ' "$NETRC_PATH" > "$TMP_PATH"
fi

{
  printf 'machine urs.earthdata.nasa.gov\n'
  printf '  login %s\n' "$EARTHDATA_USERNAME"
  printf '  password %s\n' "$EARTHDATA_PASSWORD"
} >> "$TMP_PATH"

install -m 600 "$TMP_PATH" "$NETRC_PATH"
rm -f "$TMP_PATH"

unset EARTHDATA_PASSWORD
printf 'Earthdata credentials saved to %s with mode 600.\n' "$NETRC_PATH"
