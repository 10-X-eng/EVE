#!/bin/bash
# Small per-user installer for macOS. The complete EVE payload sits next to this script.
set -euo pipefail

ADDINS="$HOME/Library/Application Support/Autodesk/Autodesk Fusion 360/API/AddIns"
MARKER="EVE 0.1.0"

fail() {
  printf 'Installation did not finish. %s\n' "$1" >&2
  exit 1
}

safe_relative_path() {
  # Reject manifest entries that could leave the payload folder.
  case "$1" in
    ""|/*|..|../*|*/..|*/../*) return 1 ;;
  esac
  return 0
}

verify_payload() {
  local source="$1" sums="$2" line digest relative actual
  if [[ ! -f "$sums" || ! -f "$source/EVE.manifest" ]]; then
    fail "Extract the entire EVE zip before running the installer."
  fi
  [[ -s "$sums" ]] || fail "The package manifest is empty."
  # Validate every listed file before changing the installation.
  while IFS= read -r line || [[ -n "$line" ]]; do
    if [[ ${#line} -lt 67 || "${line:64:2}" != "  " ]]; then
      fail "Invalid checksum manifest."
    fi
    digest="${line:0:64}"
    relative="${line:66}"
    [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "Invalid checksum manifest."
    safe_relative_path "$relative" || fail "The package contains an invalid path."
    [[ -f "$source/$relative" ]] || fail "Package verification failed. Download EVE again."
    actual="$(shasum -a 256 "$source/$relative" | cut -d ' ' -f 1)"
    [[ "$actual" == "$digest" ]] || fail "Package verification failed. Download EVE again."
  done < "$sums"
}

install_payload() {
  local package="$1" root="$2"
  local source="$package/EVE" sums="$package/SHA256SUMS"
  verify_payload "$source" "$sums"
  mkdir -p "$root"
  local destination="$root/EVE"
  local staging="$root/EVE-staging-$(uuidgen | tr -d '-')"
  local backup_root
  backup_root="$(dirname "$root")/EVE-install-backups"
  local backup="$backup_root/$(date -u +%Y%m%d-%H%M%S)-$(uuidgen | tr -d '-')"
  if [[ -d "$destination" && ! -f "$destination/eve-install-marker.txt" ]]; then
    fail "An unmanaged EVE folder already exists. Rename it before installing."
  fi
  mkdir -p "$staging"
  local line relative
  while IFS= read -r line || [[ -n "$line" ]]; do
    relative="${line:66}"
    mkdir -p "$staging/$(dirname "$relative")"
    cp "$source/$relative" "$staging/$relative"
  done < "$sums"
  # Zip extraction can drop Unix permission bits; the bundled runtime must stay executable.
  local binary
  for binary in "$staging"/runtime/bin/* "$staging"/runtime/codex-path/* "$staging"/runtime/codex-resources/zsh/bin/*; do
    if [[ -f "$binary" ]]; then
      chmod 755 "$binary"
    fi
  done
  # The payload was verified above; the download quarantine flag is no longer needed.
  xattr -dr com.apple.quarantine "$staging" 2>/dev/null || true
  printf '%s' "$MARKER" > "$staging/eve-install-marker.txt"
  if [[ -d "$destination" ]]; then
    mkdir -p "$backup_root"
    mv "$destination" "$backup"
  fi
  if ! mv "$staging" "$destination"; then
    if [[ -d "$backup" && ! -d "$destination" ]]; then
      mv "$backup" "$destination"
    fi
    fail "EVE could not be moved into place."
  fi
}

# Test mode requires an explicit destination and does not touch Fusion's installation.
if [[ $# -eq 3 && "$1" == "--test-install" ]]; then
  if install_payload "$2" "$3" 2> "$2/installer-test-error.txt"; then
    rm -f "$2/installer-test-error.txt"
    exit 0
  fi
  exit 1
fi

package="$(cd "$(dirname "$0")" && pwd)"
printf '\nMeet EVE.\nYour engineering partner inside Fusion.\nInstall EVE, sign in with ChatGPT, and start a conversation.\n\n'
printf 'Installs for your macOS account. No administrator access needed.\n'
while pgrep -x "Autodesk Fusion" > /dev/null; do
  printf '\nFusion is still running. Save your work and quit Fusion, then press Return to continue (Control-C cancels).\n'
  read -r _
done
printf '\nChecking the package and installing EVE…\n'
install_payload "$package" "$ADDINS"
printf '\nInstalled. Open Fusion, then choose EVE in the Quick Access toolbar.\n'
printf 'If needed, enable EVE under Scripts and Add-ins first.\n\nYou can close this window.\n'
