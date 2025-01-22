#!/usr/bin/env python3
"""
Hacktoberfest Topic Checker

Checks which OSS4SG repos have the "hacktoberfest" GitHub topic.
Uses token rotation for faster processing.
Includes safeguards: progress saving, error handling, rate limit checking.
"""

import json
import csv
import time
import argparse
from pathlib import Path
from datetime import datetime
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from typing import List, Dict, Optional

BASE_DIR = Path(__file__).parent

# Valid GitHub tokens (token 5 was invalid)
GITHUB_TOKENS = [
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
    "os.environ.get("GITHUB_TOKEN", "")",
]


class TokenRotator:
    """Rotate through GitHub tokens to maximize rate limits."""
    
    def __init__(self, tokens: List[str]):
        self.tokens = tokens
        self.current_idx = 0
    
    def get_token(self) -> str:
        """Get current token."""
        return self.tokens[self.current_idx]
    
    def rotate(self):
        """Move to next token."""
        self.current_idx = (self.current_idx + 1) % len(self.tokens)
    
    def get_headers(self) -> Dict[str, str]:
        """Get headers with current token."""
        return {
            "Authorization": f"token {self.get_token()}",
            "User-Agent": "Hacktoberfest-Checker/1.0",
            "Accept": "application/vnd.github.mercy-preview+json",  # Required for topics
        }


def load_oss4sg_repos(csv_path: Path) -> List[str]:
    """Load repo names from OSS4SG CSV."""
    repos = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            repo = row.get("repo_name_with_owner", "").strip()
            if repo:
                repos.append(repo)
    return repos


def load_progress(progress_file: Path) -> Dict:
    """Load progress from previous run."""
    if progress_file.exists():
        with open(progress_file) as f:
            return json.load(f)
    return {"checked": [], "results": []}


def save_progress(progress_file: Path, progress: Dict):
    """Save current progress."""
    with open(progress_file, "w") as f:
        json.dump(progress, f, indent=2)


def check_repo_topics(repo: str, rotator: TokenRotator, max_retries: int = 3) -> Optional[Dict]:
    """
    Check topics for a single repo.
    Returns dict with repo info or None on failure.
    """
    url = f"https://api.github.com/repos/{repo}/topics"
    
    for attempt in range(max_retries):
        try:
            req = Request(url, headers=rotator.get_headers())
            with urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                topics = data.get("names", [])
                
                # Check for hacktoberfest topic (case-insensitive)
                has_hacktoberfest = any(
                    "hacktoberfest" in t.lower() for t in topics
                )
                
                return {
                    "repo": repo,
                    "has_hacktoberfest": has_hacktoberfest,
                    "topics": topics,
                    "checked_at": datetime.utcnow().isoformat() + "Z",
                    "status": "success",
                }
                
        except HTTPError as e:
            if e.code == 404:
                # Repo doesn't exist or is private
                return {
                    "repo": repo,
                    "has_hacktoberfest": False,
                    "topics": [],
                    "checked_at": datetime.utcnow().isoformat() + "Z",
                    "status": "not_found",
                }
            elif e.code == 403:
                # Rate limited - rotate token and retry
                rotator.rotate()
                time.sleep(1)
            else:
                # Other error - retry with backoff
                time.sleep(2 ** attempt)
                
        except (URLError, TimeoutError) as e:
            time.sleep(2 ** attempt)
    
    # All retries failed
    return {
        "repo": repo,
        "has_hacktoberfest": False,
        "topics": [],
        "checked_at": datetime.utcnow().isoformat() + "Z",
        "status": "error",
    }


def check_all_repos(
    repos: List[str],
    rotator: TokenRotator,
    progress_file: Path,
    save_interval: int = 20,
    delay: float = 0.1,
) -> List[Dict]:
    """Check topics for all repos with progress saving."""
    
    # Load existing progress
    progress = load_progress(progress_file)
    checked_set = set(progress["checked"])
    results = progress["results"]
    
    # Filter to only unchecked repos
    remaining = [r for r in repos if r not in checked_set]
    
    if remaining:
        print(f"Checking {len(remaining)} repos ({len(checked_set)} already done)...")
    else:
        print("All repos already checked!")
        return results
    
    for i, repo in enumerate(remaining):
        # Progress update
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(remaining)} (total checked: {len(results)})")
        
        # Check repo
        result = check_repo_topics(repo, rotator)
        if result:
            results.append(result)
            checked_set.add(repo)
            progress["checked"] = list(checked_set)
            progress["results"] = results
        
        # Save progress periodically
        if (i + 1) % save_interval == 0:
            save_progress(progress_file, progress)
        
        # Small delay to be nice to API
        time.sleep(delay)
        
        # Rotate token every 100 requests to spread load
        if (i + 1) % 100 == 0:
            rotator.rotate()
    
    # Final save
    save_progress(progress_file, progress)
    print(f"  Done: {len(results)} repos checked")
    
    return results


def generate_outputs(results: List[Dict]):
    """Generate output files."""
    
    # All repos with results
    save_json(BASE_DIR / "oss4sg_hacktoberfest_repos.json", results)
    
    # CSV version
    with open(BASE_DIR / "oss4sg_hacktoberfest_repos.csv", "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["repo", "has_hacktoberfest", "topics", "status"])
        writer.writeheader()
        for r in results:
            writer.writerow({
                "repo": r["repo"],
                "has_hacktoberfest": r["has_hacktoberfest"],
                "topics": "|".join(r["topics"]),
                "status": r["status"],
            })
    
    # Only repos WITH hacktoberfest topic
    matches = [r["repo"] for r in results if r["has_hacktoberfest"]]
    save_json(BASE_DIR / "oss4sg_hacktoberfest_matches.json", matches)
    
    print(f"\nSaved:")
    print(f"  - oss4sg_hacktoberfest_repos.json/csv ({len(results)} repos)")
    print(f"  - oss4sg_hacktoberfest_matches.json ({len(matches)} matches)")


def save_json(path: Path, data):
    """Save data to JSON."""
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def main():
    parser = argparse.ArgumentParser(description="Check Hacktoberfest topics for OSS4SG repos")
    parser.add_argument("--oss4sg-csv", type=Path,
                        default=BASE_DIR.parent.parent / "OSS4SG-Project-List.csv",
                        help="Path to OSS4SG CSV")
    parser.add_argument("--delay", type=float, default=0.1,
                        help="Delay between requests")
    parser.add_argument("--save-interval", type=int, default=20,
                        help="Save progress every N repos")
    parser.add_argument("--no-resume", action="store_true",
                        help="Start fresh, ignore previous progress")
    args = parser.parse_args()
    
    progress_file = BASE_DIR / "hacktoberfest_progress.json"
    
    # Clear progress if requested
    if args.no_resume and progress_file.exists():
        progress_file.unlink()
        print("Cleared previous progress")
    
    # Load repos
    print(f"Loading OSS4SG repos from {args.oss4sg_csv}...")
    repos = load_oss4sg_repos(args.oss4sg_csv)
    print(f"  Found {len(repos)} repos")
    
    # Initialize token rotator
    rotator = TokenRotator(GITHUB_TOKENS)
    print(f"  Using {len(GITHUB_TOKENS)} GitHub tokens for rotation")
    
    # Check all repos
    results = check_all_repos(
        repos, rotator, progress_file,
        save_interval=args.save_interval,
        delay=args.delay,
    )
    
    # Generate outputs
    generate_outputs(results)
    
    # Summary
    total = len(results)
    matches = sum(1 for r in results if r["has_hacktoberfest"])
    errors = sum(1 for r in results if r["status"] == "error")
    not_found = sum(1 for r in results if r["status"] == "not_found")
    
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total repos checked:     {total}")
    print(f"With hacktoberfest:      {matches}")
    print(f"Without hacktoberfest:   {total - matches - errors - not_found}")
    print(f"Not found (404):         {not_found}")
    print(f"Errors:                  {errors}")
    
    if matches > 0:
        print(f"\nOSS4SG projects participating in Hacktoberfest:")
        for r in results:
            if r["has_hacktoberfest"]:
                print(f"  ✅ {r['repo']}")


if __name__ == "__main__":
    main()
