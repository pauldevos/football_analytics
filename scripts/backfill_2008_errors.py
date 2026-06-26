# Generate a list of failed 2008 games and re-scrape them
import csv
with open('/Users/devos/data/pfref/manifest/page_manifest_2008.csv') as f:
    errors = [r['game_id'] for r in csv.DictReader(f) if r.get('error','').strip()]
print(' '.join(errors))

# Then run --game for each, or we can add a --retry-errors 
# flag to the scraper that reads the manifest and re-runs 
# only failed games. Worth doing given you'll accumulate 
# these across years.