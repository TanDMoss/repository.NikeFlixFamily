#!/usr/bin/env bash
set -e

# Move into the script’s directory
cd "$(dirname "$0")"

# Run the update & generate script
python3 update_and_generate.py

# Pause for a keypress
echo
echo "Script execution completed. Press any key to exit."
read -n 1 -s -r