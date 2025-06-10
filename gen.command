#!/usr/bin/env bash
set -e

# Move into the script’s directory
cd "$(dirname "$0")"

# Remove any pe.cfg files throughout the tree
find . -type f -name 'pe.cfg' -exec rm -f {} +

# Remove all .bak files
find . -type f -name '*.bak' -exec rm -f {} +

# Wipe out old zip dirs, then recreate them
rm -rf repo/zips leia/zips matrix/zips
mkdir -p repo/zips leia/zips matrix/zips

# Run the Python repo generator
python3 _repo_generator.py

# Clean up any top‐level .zip files
find . -maxdepth 1 -type f -name '*.zip' -exec rm -f {} +

# Copy generated zips into this folder
cp repo/zips/repository.peno64/*.zip .