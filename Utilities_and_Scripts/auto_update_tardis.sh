#!/bin/bash

# Auto-update TARDIS Portfolio
echo "Running TARDIS Portfolio Builder to sanitize and copy files..."
python3 /home/timemachine/build_portfolio.py

echo "Committing and pushing to GitHub..."
cd /home/timemachine/TARDIS_Portfolio

git add .
git commit -m "Auto-update TARDIS Core: $(date)"
git push origin main

echo "TARDIS Portfolio updated successfully."
