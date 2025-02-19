#!/usr/bin/env python3
"""
Test all GitHub tokens (4 original + 8 new = 12 total) and identify:
1. Which tokens are valid
2. Which tokens are duplicates (same account)
3. Update config.json with unique tokens
"""

import json
import sys
import time
from pathlib import Path
import subprocess

# All tokens to test
TOKENS = {
    "original_1": "os.environ.get("GITHUB_TOKEN", "")",
    "original_2": "os.environ.get("GITHUB_TOKEN", "")",
    "original_3": "os.environ.get("GITHUB_TOKEN", "")",
    "original_4": "os.environ.get("GITHUB_TOKEN", "")",
    "new_1_maybe_dup": "os.environ.get("GITHUB_TOKEN", "")",
    "new_2": "os.environ.get("GITHUB_TOKEN", "")",
    "new_3": "os.environ.get("GITHUB_TOKEN", "")",
    "new_4": "os.environ.get("GITHUB_TOKEN", "")",
    "new_5_maybe_dup": "os.environ.get("GITHUB_TOKEN", "")",
    "new_6": "os.environ.get("GITHUB_TOKEN", "")",
    "new_7": "os.environ.get("GITHUB_TOKEN", "")",
    "new_8": "os.environ.get("GITHUB_TOKEN", "")",
}

def test_token(token_name, token_value):
    """Test a GitHub token and return account info"""
    try:
        # Use curl to test the token
        result = subprocess.run(
            [
                "curl", "-s",
                "-H", f"Authorization: token {token_value}",
                "https://api.github.com/user"
            ],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return {"name": token_name, "valid": False, "error": "curl failed"}
        
        # Parse JSON response
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            return {"name": token_name, "valid": False, "error": "Invalid JSON response"}
        
        # Check if token is valid
        if "login" in data:
            return {
                "name": token_name,
                "valid": True,
                "username": data["login"],
                "user_id": data["id"],
                "token": token_value
            }
        elif "message" in data:
            return {
                "name": token_name,
                "valid": False,
                "error": data["message"]
            }
        else:
            return {"name": token_name, "valid": False, "error": "Unknown response"}
            
    except subprocess.TimeoutExpired:
        return {"name": token_name, "valid": False, "error": "Timeout"}
    except Exception as e:
        return {"name": token_name, "valid": False, "error": str(e)}

def validate_all_tokens():
    """Test all tokens and identify duplicates"""
    
    print("="*80)
    print("GITHUB TOKEN VALIDATION")
    print("="*80)
    print(f"\nTesting {len(TOKENS)} tokens...\n")
    
    results = []
    
    for token_name, token_value in TOKENS.items():
        print(f"Testing {token_name}... ", end="", flush=True)
        result = test_token(token_name, token_value)
        results.append(result)
        
        if result["valid"]:
            print(f"✓ Valid (username: {result['username']}, id: {result['user_id']})")
        else:
            print(f"✗ Invalid ({result.get('error', 'Unknown error')})")
        
        time.sleep(0.5)  # Be nice to GitHub API
    
    # Analyze results
    valid_tokens = [r for r in results if r["valid"]]
    invalid_tokens = [r for r in results if not r["valid"]]
    
    print(f"\n{'='*80}")
    print("RESULTS:")
    print(f"{'='*80}")
    print(f"Valid tokens:   {len(valid_tokens)}")
    print(f"Invalid tokens: {len(invalid_tokens)}")
    
    # Find duplicates by user_id
    user_id_map = {}
    for token in valid_tokens:
        user_id = token["user_id"]
        if user_id not in user_id_map:
            user_id_map[user_id] = []
        user_id_map[user_id].append(token)
    
    # Identify duplicates
    duplicates = {uid: tokens for uid, tokens in user_id_map.items() if len(tokens) > 1}
    unique_tokens = []
    
    print(f"\n{'='*80}")
    print("DUPLICATE ANALYSIS:")
    print(f"{'='*80}")
    
    if duplicates:
        print(f"Found {len(duplicates)} accounts with multiple tokens:")
        for user_id, tokens in duplicates.items():
            print(f"\n  Account {tokens[0]['username']} (id: {user_id}):")
            for token in tokens:
                print(f"    - {token['name']}")
            # Keep first token only
            unique_tokens.append(tokens[0])
    else:
        print("No duplicates found!")
    
    # Add non-duplicate tokens
    for user_id, tokens in user_id_map.items():
        if len(tokens) == 1:
            unique_tokens.append(tokens[0])
    
    print(f"\n{'='*80}")
    print("UNIQUE TOKENS:")
    print(f"{'='*80}")
    print(f"Total unique accounts: {len(unique_tokens)}")
    
    for i, token in enumerate(unique_tokens, 1):
        print(f"  {i}. {token['username']} ({token['name']})")
    
    # Update config.json
    config_path = Path(__file__).parent.parent / "05_contributor_journey_extraction" / "config.json"
    
    if not config_path.exists():
        print(f"\nERROR: config.json not found at {config_path}")
        return None
    
    with open(config_path, 'r') as f:
        config = json.load(f)
    
    # Update tokens and max_workers
    config["github_tokens"] = [t["token"] for t in unique_tokens]
    config["max_workers"] = len(unique_tokens)
    
    with open(config_path, 'w') as f:
        json.dump(config, f, indent=2)
    
    print(f"\n{'='*80}")
    print("CONFIG UPDATE:")
    print(f"{'='*80}")
    print(f"Updated {config_path}")
    print(f"  - github_tokens: {len(unique_tokens)} unique tokens")
    print(f"  - max_workers: {len(unique_tokens)}")
    
    # Save validation report
    report_path = Path(__file__).parent / "token_validation_report.json"
    with open(report_path, 'w') as f:
        json.dump({
            "total_tested": len(TOKENS),
            "valid": len(valid_tokens),
            "invalid": len(invalid_tokens),
            "unique_accounts": len(unique_tokens),
            "duplicates": len(duplicates),
            "unique_tokens": [
                {
                    "username": t["username"],
                    "user_id": t["user_id"],
                    "token_name": t["name"]
                }
                for t in unique_tokens
            ],
            "invalid_tokens": [
                {
                    "name": t["name"],
                    "error": t.get("error", "Unknown")
                }
                for t in invalid_tokens
            ]
        }, f, indent=2)
    
    print(f"\nValidation report saved to: {report_path}")
    
    return {
        "unique_count": len(unique_tokens),
        "duplicate_count": len(duplicates),
        "invalid_count": len(invalid_tokens)
    }

if __name__ == "__main__":
    try:
        results = validate_all_tokens()
        if results:
            print(f"\n✓ Token validation completed successfully!")
            print(f"  {results['unique_count']} unique tokens configured")
            sys.exit(0)
        else:
            print("\n✗ Token validation failed")
            sys.exit(1)
    except Exception as e:
        print(f"\n✗ Error validating tokens: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
