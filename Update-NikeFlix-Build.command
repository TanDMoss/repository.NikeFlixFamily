#!/usr/bin/env bash
set -e

# Move into the script’s directory
cd "$(dirname "$0")"

# Run the version updater
python3 update_versions.py

# Pause for a keypress
echo
echo "Script execution completed. Press any key to exit."
read -n 1 -s -r