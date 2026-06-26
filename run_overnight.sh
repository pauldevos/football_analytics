#!/bin/bash
# Overnight scraping run — runs all pending pulls sequentially.
# Each script is idempotent: already-pulled data is skipped automatically.
#
# Usage:
#   chmod +x run_overnight.sh
#   ./run_overnight.sh 2>&1 | tee logs/overnight_$(date +%Y%m%d_%H%M).log

set -o pipefail
cd "$(dirname "$0")"

log() { echo ""; echo "========================================"; echo "$1  [$(date '+%H:%M:%S')]"; echo "========================================"; }

log "START overnight scraping"

log "1/4  Player stats — all types, all years (skips already-pulled)"
python scripts/scrape_player_stats.py

log "2/4  Team stats — offense + defense, 2025→1950"
python scripts/scrape_team_stats.py

log "3/4  Coaches — pull all HCs (discovers tree coaches along the way)"
python scripts/scrape_coaches.py --pull

log "4/4  Coaches — second pass to pull tree coaches found in step 3"
python scripts/scrape_coaches.py --pull

log "DONE overnight scraping"
