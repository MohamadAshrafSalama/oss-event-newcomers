#!/usr/bin/env python3
"""
Create balanced contributor selection:
- Mentorship (GSoC + LFX): ~1,339 contributors
- Non-mentorship (24PR + HF): ~1,339 contributors (sample HF to match)
"""

import json
from pathlib import Path

def main():
    print("="*80)
    print("BALANCED CONTRIBUTOR SELECTION")
    print("="*80)
    
    # Fixed numbers
    gsoc_count = 1123
    lfx_count = 216
    pr24_count = 479
    hf_available = 5126
    
    # Calculate target
    mentorship_total = gsoc_count + lfx_count
    non_mentorship_current = pr24_count + hf_available
    
    # We want non-mentorship ≈ mentorship
    target_non_mentorship = mentorship_total
    hf_needed = target_non_mentorship - pr24_count
    
    print(f"\n{'='*80}")
    print("CURRENT STATE")
    print(f"{'='*80}")
    print(f"\nMentorship Events:")
    print(f"  GSoC (2+ contributions):  {gsoc_count:5d}")
    print(f"  LFX (no filter):          {lfx_count:5d}")
    print(f"  ─────────────────────────────")
    print(f"  Total Mentorship:         {mentorship_total:5d}")
    
    print(f"\nNon-Mentorship Events:")
    print(f"  24PR (4+ PRs):            {pr24_count:5d}")
    print(f"  Hacktoberfest (4+ PRs):   {hf_available:5d}")
    print(f"  ─────────────────────────────")
    print(f"  Total Non-Mentorship:     {non_mentorship_current:5d}")
    
    print(f"\n{'='*80}")
    print("BALANCING STRATEGY")
    print(f"{'='*80}")
    
    print(f"\nTarget: Match mentorship and non-mentorship counts")
    print(f"  Target non-mentorship: {target_non_mentorship}")
    print(f"  24PR (fixed):          {pr24_count}")
    print(f"  Hacktoberfest needed:  {hf_needed}")
    
    # Sampling strategy for Hacktoberfest
    # 50% top + 50% random (as per original plan)
    hf_top_half = hf_needed // 2
    hf_random_half = hf_needed - hf_top_half
    
    print(f"\nHacktoberfest sampling:")
    print(f"  Take {hf_needed} from {hf_available} available")
    print(f"  Strategy: 50% top + 50% random")
    print(f"    Top {hf_top_half} by activity")
    print(f"    Random {hf_random_half} from remaining")
    
    print(f"\n{'='*80}")
    print("FINAL BALANCED DATASET")
    print(f"{'='*80}")
    
    final_mentorship = mentorship_total
    final_non_mentorship = pr24_count + hf_needed
    final_total = final_mentorship + final_non_mentorship
    
    print(f"\nMentorship Events:")
    print(f"  GSoC:              {gsoc_count:5d}")
    print(f"  LFX:               {lfx_count:5d}")
    print(f"  ─────────────────────────")
    print(f"  Subtotal:          {final_mentorship:5d}")
    
    print(f"\nNon-Mentorship Events:")
    print(f"  24PR:              {pr24_count:5d}")
    print(f"  Hacktoberfest:     {hf_needed:5d}")
    print(f"  ─────────────────────────")
    print(f"  Subtotal:          {final_non_mentorship:5d}")
    
    print(f"\n{'='*80}")
    print(f"  TOTAL EVENT:       {final_total:5d}")
    print(f"{'='*80}")
    
    print(f"\nOrganic Matching:")
    print(f"  Will match {final_total} organic contributors")
    print(f"  from the same projects")
    print(f"\n{'='*80}")
    print(f"  FINAL DATASET:     {final_total * 2:5d} contributors")
    print(f"  ({final_total} event + {final_total} organic)")
    print(f"{'='*80}")
    
    # Corpus info
    print(f"\n{'='*80}")
    print("CORPUS INFORMATION")
    print(f"{'='*80}")
    print(f"  Projects: 435 total")
    print(f"    - 50 Hacktoberfest (4+ PRs)")
    print(f"    - 50 24 Pull Requests (4+ PRs)")
    print(f"    - 50 LFX (no filter)")
    print(f"    - 235 GSoC (2+ contributions)")
    print(f"    - 66 additional OSS4SG")
    print(f"    (369 unique from events + 66 OSS4SG)")
    
    return {
        'gsoc': gsoc_count,
        'lfx': lfx_count,
        'pr24': pr24_count,
        'hf': hf_needed,
        'total_event': final_total,
        'total_with_organic': final_total * 2
    }

if __name__ == "__main__":
    result = main()
    print(f"\n✓ Balanced selection calculated")
    print(f"  Event contributors: {result['total_event']}")
    print(f"  Total dataset: {result['total_with_organic']}")
