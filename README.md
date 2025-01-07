# Event-Based vs Organic OSS Newcomers

Replication package for the EASE 2026 short paper:

> **"Do Structured Entry Points Help? Comparing Event-Based and Organic Newcomers in Open Source"**

## Overview

This study compares newcomers who joined OSS projects through structured events
(GSoC, LFX Mentorship, Hacktoberfest, 24 Pull Requests) against organically
joining contributors matched on project and prior activity level. We examine
retention, core-contributor achievement, and early engagement patterns across
a corpus of 385 OSS repositories and ~1,200 matched contributor pairs.

## Repository Structure

```
src/
  events/           # Event participant extraction (GSoC, LFX, Hacktoberfest, 24PR, MLH)
  consolidation/    # Merging event lists, GitHub metadata fetch
  matching/         # Contributor selection and organic matching
  journeys/         # Contribution journey extraction (24-month window)
  core/             # Core contributor identification
  analysis/         # Statistical analyses (RQ1–RQ3)
  visualization/    # Figures for the paper

scripts/            # Numbered pipeline scripts (00–91)
replication_package/
  scripts/          # Clean replication scripts for reviewers
  run_all.py        # One-command full replication

lab_member/         # Starter scripts for lab collaborators
config/             # YAML configuration
```

## Replication

### Requirements

- Python 3.10+
- GitHub personal access tokens (place in `.env` as `GITHUB_TOKEN_1`, `GITHUB_TOKEN_2`, ...)

### Quick Start

```bash
pip install -e .
cp .env.example .env   # fill in tokens
python replication_package/run_all.py
```

### Step-by-Step

```bash
# 1. Validate dataset
python replication_package/scripts/00_dataset_validation.py

# 2. Activity profiles (RQ1)
python replication_package/scripts/01_activity_profiles.py

# 3. Early engagement patterns (RQ2)
python replication_package/scripts/02_early_engagement_patterns.py

# 4. Core rate and time-to-core (RQ3)
python replication_package/scripts/03_core_rate_and_ttc.py

# 5. Survival analysis
python replication_package/scripts/04_survival_analysis.py

# 6. Pattern-outcome ranking (Scott-Knott)
python replication_package/scripts/05_pattern_outcome_ranking.py
```

## Event Programs

| Program | Years | Description |
|---------|-------|-------------|
| GSoC | 2019–2023 | Google Summer of Code — stipend-based mentored projects |
| LFX | 2020–2023 | Linux Foundation mentorship program |
| Hacktoberfest | 2019–2023 | October PR contribution event (DigitalOcean) |
| 24 Pull Requests | 2019–2022 | December PR advent calendar |
| MLH Fellowship | 2020–2023 | Major League Hacking open-source fellowship |

## Citation

```bibtex
@inproceedings{ouf2026event,
  title     = {Do Structured Entry Points Help? Comparing Event-Based and
               Organic Newcomers in Open Source},
  author    = {Ouf, Mohamed and ...},
  booktitle = {Proceedings of the International Conference on Evaluation and
               Assessment in Software Engineering (EASE)},
  year      = {2026}
}
```

## License

MIT
