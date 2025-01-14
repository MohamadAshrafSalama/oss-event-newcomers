import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


def load_orgs(path: Path) -> List[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def write_csv(path: Path, records: List[Dict[str, Any]], fieldnames: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in records:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def _as_list(value: Any) -> List[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def build_org_year_records(orgs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for org in orgs:
        years = org.get("years") or {}
        for year_str, ydata in years.items():
            projects = _as_list((ydata or {}).get("projects"))
            num_projects = (ydata or {}).get("num_projects", len(projects))
            with_code_url = sum(1 for p in projects if p.get("code_url"))
            record = {
                "org_name": org.get("name"),
                "year": int(year_str),
                "org_url": org.get("url"),
                "description": org.get("description"),
                "category": org.get("category"),
                "technologies": org.get("technologies") or [],
                "topics": org.get("topics") or [],
                "twitter_url": org.get("twitter_url"),
                "blog_url": org.get("blog_url"),
                "num_projects": num_projects,
                "project_count_with_code_url": with_code_url,
            }
            records.append(record)
    return records


def build_project_records(orgs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for org in orgs:
        base = {
            "org_name": org.get("name"),
            "org_url": org.get("url"),
            "description": org.get("description"),
            "category": org.get("category"),
            "technologies": org.get("technologies") or [],
            "topics": org.get("topics") or [],
            "twitter_url": org.get("twitter_url"),
            "blog_url": org.get("blog_url"),
        }
        years = org.get("years") or {}
        for year_str, ydata in years.items():
            year = int(year_str)
            projects = _as_list((ydata or {}).get("projects"))
            for proj in projects:
                record = {
                    **base,
                    "year": year,
                    "project_title": proj.get("title"),
                    "student_name": proj.get("student_name"),
                    "code_url": proj.get("code_url"),
                }
                records.append(record)
    return records


def _normalize_github_url(url: str) -> str:
    normalized = url.strip().lower()
    for prefix in ("https://", "http://"):
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
    if normalized.startswith("www."):
        normalized = normalized[4:]
    if normalized.endswith(".git"):
        normalized = normalized[:-4]
    while normalized.endswith("/"):
        normalized = normalized[:-1]
    return normalized


def _is_github_url(url: Optional[str]) -> bool:
    if not url:
        return False
    return "github.com" in url.lower()


def extract_github_records(orgs: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}

    def update_entry(
        raw_url: str,
        org_name: Optional[str],
        year: Optional[int],
        source: str,
        project_title: Optional[str] = None,
    ) -> None:
        norm = _normalize_github_url(raw_url)
        if norm not in agg:
            agg[norm] = {
                "github_url": raw_url,
                "normalized": norm,
                "org_names": set(),
                "sources": set(),
                "years": set(),
                "total_gsoc_projects": 0,
                "project_titles": set(),
            }
        entry = agg[norm]
        if org_name:
            entry["org_names"].add(org_name)
        entry["sources"].add(source)
        if year:
            entry["years"].add(year)
        if source == "code_url":
            entry["total_gsoc_projects"] += 1
            if project_title:
                entry["project_titles"].add(project_title)

    for org in orgs:
        org_name = org.get("name")
        years = org.get("years") or {}
        org_url = org.get("url")
        if _is_github_url(org_url):
            for year_key in years.keys():
                update_entry(org_url, org_name, int(year_key), "org_url")

        for year_str, ydata in years.items():
            year = int(year_str)
            projects = _as_list((ydata or {}).get("projects"))
            for proj in projects:
                code_url = proj.get("code_url")
                if _is_github_url(code_url):
                    update_entry(code_url, org_name, year, "code_url", proj.get("title"))

    records: List[Dict[str, Any]] = []
    for entry in agg.values():
        records.append(
            {
                "github_url": entry["github_url"],
                "normalized": entry["normalized"],
                "org_names": sorted(entry["org_names"]),
                "years": sorted(entry["years"]),
                "sources": sorted(entry["sources"]),
                "total_gsoc_projects": entry["total_gsoc_projects"],
                "project_titles": sorted(entry["project_titles"]),
            }
        )
    records.sort(key=lambda r: r["normalized"])
    return records


def load_our_projects(csv_path: Path, url_column: str) -> List[str]:
    urls: List[str] = []
    with csv_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            value = row.get(url_column)
            if value:
                val = value.strip()
                if not val:
                    continue
                # If the value is of the form owner/repo, expand to full GitHub URL.
                if not val.startswith(("http://", "https://")) and "/" in val:
                    val = f"https://github.com/{val}"
                urls.append(val)
    return urls


def match_projects(
    gsoc_records: List[Dict[str, Any]],
    our_urls: List[str],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    our_normalized = {_normalize_github_url(u): u for u in our_urls if u}

    matches: List[Dict[str, Any]] = []
    for rec in gsoc_records:
        normalized = rec["normalized"]
        if normalized in our_normalized:
            matches.append(
                {
                    "our_project_url": our_normalized[normalized],
                    "gsoc_github_url": rec["github_url"],
                    "gsoc_org_names": rec.get("org_names", []),
                    "years_participated": rec.get("years", []),
                    "match_type": "exact",
                    "match_confidence": "high",
                }
            )

    summary = {
        "total_our_projects": len(our_urls),
        "total_gsoc_github_urls": len(gsoc_records),
        "total_matches": len(matches),
        "match_rate": f"{(len(matches) / len(our_urls) * 100):.2f}%" if our_urls else "n/a",
    }
    return matches, summary


def stringify_lists_for_csv(records: List[Dict[str, Any]], keys: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for rec in records:
        new_rec = dict(rec)
        for key in keys:
            value = new_rec.get(key)
            if isinstance(value, list):
                new_rec[key] = "|".join(str(v) for v in value)
        out.append(new_rec)
    return out


def run_pipeline(
    orgs_path: Path,
    out_dir: Path,
    run_github_extraction: bool,
    our_projects_csv: Optional[Path],
    our_projects_column: str,
) -> None:
    orgs = load_orgs(orgs_path)

    org_year_records = build_org_year_records(orgs)
    write_json(out_dir / "gsoc_org_years.json", org_year_records)
    write_csv(
        out_dir / "gsoc_org_years.csv",
        stringify_lists_for_csv(org_year_records, ["technologies", "topics"]),
        [
            "org_name",
            "year",
            "org_url",
            "description",
            "category",
            "technologies",
            "topics",
            "twitter_url",
            "blog_url",
            "num_projects",
            "project_count_with_code_url",
        ],
    )

    project_records = build_project_records(orgs)
    write_json(out_dir / "gsoc_projects.json", project_records)
    write_csv(
        out_dir / "gsoc_projects.csv",
        stringify_lists_for_csv(project_records, ["technologies", "topics"]),
        [
            "org_name",
            "year",
            "project_title",
            "student_name",
            "code_url",
            "org_url",
            "description",
            "category",
            "technologies",
            "topics",
            "twitter_url",
            "blog_url",
        ],
    )

    github_records: List[Dict[str, Any]] = []
    if run_github_extraction:
        github_records = extract_github_records(orgs)
        write_json(out_dir / "gsoc_github_urls_extracted.json", github_records)
        write_csv(
            out_dir / "gsoc_github_urls_extracted.csv",
            stringify_lists_for_csv(github_records, ["org_names", "years", "sources", "project_titles"]),
            [
                "github_url",
                "normalized",
                "org_names",
                "years",
                "sources",
                "total_gsoc_projects",
                "project_titles",
            ],
        )

    if our_projects_csv:
        if not github_records:
            github_records = extract_github_records(orgs)
        our_urls = load_our_projects(our_projects_csv, our_projects_column)
        matches, summary = match_projects(github_records, our_urls)
        write_json(out_dir / "our_projects_in_gsoc.json", matches)
        write_json(out_dir / "gsoc_matching_summary.json", summary)


def parse_args() -> argparse.Namespace:
    base_dir = Path(__file__).parent.resolve()
    parser = argparse.ArgumentParser(description="GSoC data extraction and matching.")
    parser.add_argument(
        "--orgs-json",
        type=Path,
        default=base_dir / "gsoc_all_organizations.json",
        help="Path to organizations.json from api.gsocorganizations.dev",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=base_dir,
        help="Output directory for generated datasets",
    )
    parser.add_argument(
        "--run-github-extraction",
        action="store_true",
        help="Extract GitHub URLs into gsoc_github_urls_extracted.*",
    )
    parser.add_argument(
        "--project-csv",
        type=Path,
        default=None,
        help="Path to our projects CSV (requires column specified by --project-url-column)",
    )
    parser.add_argument(
        "--project-url-column",
        type=str,
        default="github_url",
        help="Column name in our project CSV that contains GitHub URLs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    run_pipeline(
        orgs_path=args.orgs_json,
        out_dir=args.out_dir,
        run_github_extraction=args.run_github_extraction,
        our_projects_csv=args.project_csv,
        our_projects_column=args.project_url_column,
    )


if __name__ == "__main__":
    main()
