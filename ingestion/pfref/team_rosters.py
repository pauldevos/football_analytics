"""
Team roster scraper module for Pro Football Reference.

This module provides functions to scrape and manage team rosters from
pro-football-reference.com, including robust table extraction and parsing.
"""

import csv
import os
import pathlib
import random
import re
import time
import urllib.parse
from typing import Optional, Set, Tuple, List

import pandas as pd
import requests
from bs4 import BeautifulSoup, Comment


def extract_roster_table(soup: BeautifulSoup):
    """
    Extract roster table from BeautifulSoup object.
    
    Tries direct find first, then searches HTML comments for the table.
    
    Args:
        soup: BeautifulSoup object of the page
        
    Returns:
        BeautifulSoup table element or None if not found
    """
    # 1) Try direct find first
    table = soup.find('div', {'id': 'div_roster'})
    if table:
        t = table.find('table')
        if t:
            return t

    t = soup.find('table', {'id': 'roster'})
    if t:
        return t

    # 2) Fall back to searching HTML comments for the table
    comments = soup.find_all(
        string=lambda text: isinstance(text, Comment) 
        and ("div_roster" in text or 'id="roster"' in text)
    )
    for comment in comments:
        commented_soup = BeautifulSoup(comment, 'html.parser')
        roster_div = commented_soup.find('div', {'id': 'div_roster'})
        if roster_div:
            t = roster_div.find('table')
            if t:
                return t
        t = commented_soup.find('table', {'id': 'roster'})
        if t:
            return t

    return None


def parse_table_manual(table) -> pd.DataFrame:
    """
    Parse roster HTML table into a pandas DataFrame.

    Args:
        table: BeautifulSoup table element

    Returns:
        DataFrame with roster data including player_link and player_id columns

    Raises:
        ValueError: If no rows found when parsing
    """
    # Headers: prefer thead th, fallback to first row
    headers = []
    thead = table.find('thead')
    if thead:
        headers = [th.get_text(strip=True) for th in thead.find_all('th')]
    else:
        first_row = table.find('tr')
        if first_row:
            headers = [cell.get_text(strip=True) for cell in first_row.find_all(['th', 'td'])]

    # Rows: use tbody if present, else all tr except header
    rows = []
    player_links = []
    tbody = table.find('tbody')
    trs = tbody.find_all('tr') if tbody else table.find_all('tr')
    for tr in trs:
        cells = [cell.get_text(strip=True) for cell in tr.find_all(['th', 'td'])]
        if not cells:
            continue
        rows.append(cells)
        # Extract the first /players/... href in this row
        href = ""
        for a in tr.find_all('a', href=True):
            if '/players/' in a['href']:
                href = a['href'].strip()
                break
        player_links.append(href)

    if not rows:
        raise ValueError('No rows found when parsing table')

    # Normalize rows to have the same length as headers
    max_cols = max(len(r) for r in rows)
    if not headers or len(headers) < max_cols:
        headers = headers + [f'col{i}' for i in range(len(headers) + 1, max_cols + 1)]

    # Trim or pad rows
    norm_rows = [
        r + [''] * (max_cols - len(r)) if len(r) < max_cols else r[:max_cols]
        for r in rows
    ]

    df = pd.DataFrame(norm_rows, columns=headers[:max_cols])

    # Append player_link and player_id (empty string when no link found)
    df['player_link'] = player_links
    df['player_id'] = df['player_link'].str.extract(r'/([^/]+)\.htm$').fillna('')

    return df


def canonicalize_roster_url(url: str) -> str:
    """
    Canonicalize a season URL to a roster URL.
    
    Args:
        url: Season URL from pro-football-reference.com
        
    Returns:
        Canonicalized roster URL
    """
    url = url.strip()
    p = urllib.parse.urlparse(url)
    scheme = p.scheme or 'https'
    netloc = p.netloc.lower()
    path = p.path.rstrip('/')
    
    if path.endswith('.htm'):
        roster_path = path.replace('.htm', '_roster.htm')
    else:
        roster_path = path + '_roster.htm'
    
    canon = urllib.parse.urlunparse((scheme, netloc, roster_path, '', '', ''))
    return canon


def get_existing_rosters(roster_dir: pathlib.Path) -> Set[Tuple[str, int]]:
    """
    Get set of (team_code, year) tuples that already have roster files.
    
    Args:
        roster_dir: Directory containing roster CSV files
        
    Returns:
        Set of (team_code, year) tuples
    """
    existing = set()
    if not roster_dir.exists():
        return existing
    
    for file in roster_dir.glob('*_*_roster.csv'):
        parts = file.stem.split('_')
        if len(parts) >= 2:
            team_code = parts[0]
            try:
                year = int(parts[1])
                existing.add((team_code, year))
            except ValueError:
                pass
    
    return existing


def download_rosters(
    season_urls: List[str],
    roster_dir: pathlib.Path,
    limit: Optional[int] = None,
    overwrite: bool = False,
    max_attempts: int = 3,
    verbose: bool = True
) -> dict:
    """
    Download rosters for all team-season URLs.
    
    Args:
        season_urls: List of season URLs from pro-football-reference.com
        roster_dir: Directory to save roster CSVs
        limit: Maximum number of URLs to process (None = all)
        overwrite: Whether to re-download existing rosters
        max_attempts: Maximum retry attempts per URL
        verbose: Whether to print progress
        
    Returns:
        Dictionary with 'success', 'skipped', 'failed', 'errors' counts
    """
    roster_dir.mkdir(parents=True, exist_ok=True)
    
    # Build roster URLs and dedupe
    def normalize_url_list(urls: List[str]) -> List[Tuple[str, str]]:
        seen = set()
        normalized = []
        duplicates = 0
        
        for u in urls:
            if not isinstance(u, str):
                continue
            u_strip = u.strip()
            if not u_strip:
                continue
            
            roster_url = canonicalize_roster_url(u_strip)
            if roster_url in seen:
                duplicates += 1
                continue
            
            seen.add(roster_url)
            normalized.append((u_strip, roster_url))
        
        if verbose:
            print(f'Original URLs: {len(urls)}  Unique roster URLs: {len(normalized)}  '
                  f'Duplicates skipped: {duplicates}')
        
        return normalized
    
    normalized = normalize_url_list(season_urls)
    
    stats = {
        'success': 0,
        'skipped': 0,
        'failed': 0,
        'errors': []
    }
    
    total = len(normalized)
    
    for idx, (season_url, roster_url) in enumerate(normalized):
        if limit and idx >= limit:
            break
        
        # Derive filename from season URL
        parsed = urllib.parse.urlparse(season_url)
        parts = parsed.path.strip('/').split('/')
        team_code = parts[1] if len(parts) >= 2 else 'team'
        year_part = parts[-1].replace('.htm', '')
        out_path = roster_dir.joinpath(f"{team_code}_{year_part}_roster.csv")
        
        if out_path.exists() and not overwrite:
            if verbose:
                print(f"[{idx + 1}/{total}] Skipping {team_code} {year_part}: "
                      f"{out_path.name} already exists")
            stats['skipped'] += 1
            continue
        
        attempt = 0
        success = False
        
        while attempt < max_attempts and not success:
            attempt += 1
            time.sleep(random.uniform(1.25, 3.0))
            
            try:
                rr = requests.get(roster_url, timeout=10)
                
                if rr.status_code == 429:
                    backoff = 5 * attempt
                    if verbose:
                        print(f"429 rate limited for {roster_url}. "
                              f"Backing off {backoff}s (attempt {attempt})")
                    time.sleep(backoff)
                    continue
                
                rr.raise_for_status()
                
                page_soup = BeautifulSoup(rr.content, 'html.parser')
                roster_table = extract_roster_table(page_soup)
                
                if roster_table is None:
                    error_msg = f"No roster table found for {team_code} {year_part}"
                    if verbose:
                        print(f"[{idx + 1}/{total}] {error_msg}")
                    stats['errors'].append(error_msg)
                    break
                
                df = parse_table_manual(roster_table)
                roster_dir.mkdir(parents=True, exist_ok=True)
                df.to_csv(out_path, index=False)
                
                if verbose:
                    print(f"[{idx + 1}/{total}] Saved roster for {team_code} {year_part} "
                          f"-> {out_path.name} (rows={len(df)})")
                
                stats['success'] += 1
                success = True
                
            except Exception as e:
                if verbose:
                    print(f"[{idx + 1}/{total}] Error fetching/parsing {roster_url} "
                          f"(attempt {attempt}): {e}")
                stats['errors'].append(f"{team_code} {year_part}: {str(e)}")
                time.sleep(2 * attempt)
        
        if not success:
            if verbose:
                print(f"[{idx + 1}/{total}] Failed to retrieve roster for {team_code} "
                      f"{year_part} after {attempt} attempts")
            stats['failed'] += 1
    
    if verbose:
        print(f"\nBatch download complete.")
        print(f"  Success: {stats['success']}")
        print(f"  Skipped: {stats['skipped']}")
        print(f"  Failed: {stats['failed']}")
        if stats['errors']:
            print(f"  Errors: {len(stats['errors'])}")
    
    return stats


def download_missing_rosters(
    season_urls: List[str],
    roster_dir: pathlib.Path,
    limit: Optional[int] = None,
    max_attempts: int = 3,
    verbose: bool = True
) -> dict:
    """
    Download only rosters that don't already exist in roster_dir.
    
    Args:
        season_urls: List of season URLs from pro-football-reference.com
        roster_dir: Directory to save roster CSVs (and check for existing files)
        limit: Maximum number of URLs to process (None = all)
        max_attempts: Maximum retry attempts per URL
        verbose: Whether to print progress
        
    Returns:
        Dictionary with stats about the download operation
    """
    # Get existing rosters
    existing = get_existing_rosters(roster_dir)
    
    # Filter season_urls to only those missing
    normalized = []
    for u in season_urls:
        if not isinstance(u, str):
            continue
        u_strip = u.strip()
        if not u_strip:
            continue
        
        parsed = urllib.parse.urlparse(u_strip)
        parts = parsed.path.strip('/').split('/')
        team_code = parts[1] if len(parts) >= 2 else None
        
        if not team_code:
            continue
        
        year_part = parts[-1].replace('.htm', '')
        try:
            year = int(year_part)
            if (team_code, year) not in existing:
                roster_url = canonicalize_roster_url(u_strip)
                normalized.append((u_strip, roster_url, team_code, year))
        except ValueError:
            pass
    
    if verbose:
        print(f"Found {len(existing)} existing rosters in {roster_dir}")
        print(f"Need to download {len(normalized)} missing rosters")
    
    # Now download the missing ones
    return download_rosters(
        [url for _, _, _, _ in normalized],  # Just pass back the season URLs
        roster_dir,
        limit=limit,
        overwrite=False,
        max_attempts=max_attempts,
        verbose=verbose
    )
