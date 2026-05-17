#!/usr/bin/env python3
"""Validate knowledge entry JSON files."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


REQUIRED_FIELDS: dict[str, type] = {
    "id": str,
    "title": str,
    "source_url": str,
    "summary": str,
    "tags": list,
    "status": str,
}

VALID_STATUSES = {"draft", "review", "published", "archived"}
VALID_AUDIENCES = {"beginner", "intermediate", "advanced"}
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+-\d{8}-\d{3}$")
URL_PATTERN = re.compile(r"^https?://")


def _check_id(value: str) -> list[str]:
    errors = []
    if isinstance(value, str) and not ID_PATTERN.match(value):
        errors.append(
            f"Invalid id format '{value}'. Expected: {{source}}-{{YYYYMMDD}}-{{NNN}} "
            "(e.g., github-20260317-001)"
        )
    return errors


def _check_url(value: str) -> list[str]:
    errors = []
    if isinstance(value, str) and not URL_PATTERN.match(value):
        errors.append(f"Invalid source_url '{value}'. Expected: https?://...")
    return errors


def _check_summary(value: str) -> list[str]:
    errors = []
    if isinstance(value, str) and len(value) < 20:
        errors.append(
            f"Summary too short ({len(value)} chars). Minimum 20 characters required."
        )
    return errors


def _check_tags(value: list[Any]) -> list[str]:
    errors = []
    if isinstance(value, list) and len(value) < 1:
        errors.append("Tags must contain at least 1 item.")
    return errors


def _check_status(value: str) -> list[str]:
    errors = []
    if isinstance(value, str) and value not in VALID_STATUSES:
        errors.append(
            f"Invalid status '{value}'. Must be one of: {', '.join(sorted(VALID_STATUSES))}"
        )
    return errors


def _check_score(data: dict[str, Any]) -> list[str]:
    errors = []
    if "score" not in data:
        return errors
    score = data["score"]
    if not isinstance(score, (int, float)):
        errors.append(
            f"Invalid score type: expected int or float, got {type(score).__name__}"
        )
    elif score < 1 or score > 10:
        errors.append(f"Score out of range ({score}). Must be between 1 and 10.")
    return errors


def _check_audience(data: dict[str, Any]) -> list[str]:
    errors = []
    if "audience" not in data:
        return errors
    audience = data["audience"]
    if not isinstance(audience, str):
        errors.append(
            f"Invalid audience type: expected str, got {type(audience).__name__}"
        )
    elif audience not in VALID_AUDIENCES:
        errors.append(
            f"Invalid audience '{audience}'. Must be one of: "
            f"{', '.join(sorted(VALID_AUDIENCES))}"
        )
    return errors


def validate_file(path: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []

    if not path.exists():
        errors.append(f"File not found: {path}")
        return False, errors

    if not path.is_file():
        errors.append(f"Not a file: {path}")
        return False, errors

    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        errors.append(f"Invalid JSON: {exc}")
        return False, errors
    except OSError as exc:
        errors.append(f"Cannot read file: {exc}")
        return False, errors

    if not isinstance(data, dict):
        errors.append(f"JSON root must be an object, got {type(data).__name__}")
        return False, errors

    for field, expected_type in REQUIRED_FIELDS.items():
        if field not in data:
            errors.append(f"Missing required field: '{field}'")
        elif not isinstance(data[field], expected_type):
            actual_type = type(data[field]).__name__
            errors.append(
                f"Invalid type for '{field}': expected {expected_type.__name__}, got {actual_type}"
            )

    if "id" in data and isinstance(data["id"], str):
        errors.extend(_check_id(data["id"]))

    if "source_url" in data and isinstance(data["source_url"], str):
        errors.extend(_check_url(data["source_url"]))

    if "summary" in data and isinstance(data["summary"], str):
        errors.extend(_check_summary(data["summary"]))

    if "tags" in data and isinstance(data["tags"], list):
        errors.extend(_check_tags(data["tags"]))

    if "status" in data and isinstance(data["status"], str):
        errors.extend(_check_status(data["status"]))

    errors.extend(_check_score(data))
    errors.extend(_check_audience(data))

    return len(errors) == 0, errors


def _is_glob(pattern: str) -> bool:
    return "*" in pattern or "?" in pattern or "[" in pattern


def collect_files(patterns: list[str]) -> list[Path]:
    files: list[Path] = []
    seen: set[Path] = set()

    for pattern in patterns:
        p = Path(pattern)
        if _is_glob(pattern):
            matches = list(Path(".").glob(pattern))
            if not matches:
                print(f"Warning: no files matched pattern '{pattern}'", file=sys.stderr)
            for match in matches:
                if match.is_file() and match not in seen:
                    files.append(match)
                    seen.add(match)
        elif p.exists():
            if p.is_file() and p not in seen:
                files.append(p)
                seen.add(p)
            elif p.is_dir():
                print(f"Warning: '{pattern}' is a directory, skipping", file=sys.stderr)
        else:
            matches = list(Path(".").glob(pattern))
            if matches:
                for match in matches:
                    if match.is_file() and match not in seen:
                        files.append(match)
                        seen.add(match)
            else:
                print(f"Warning: file not found '{pattern}'", file=sys.stderr)

    return files


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate knowledge entry JSON files."
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="JSON file(s) to validate. Supports wildcards (e.g., *.json).",
    )
    args = parser.parse_args()

    files = collect_files(args.files)

    if not files:
        print("Error: No valid files to validate.", file=sys.stderr)
        return 1

    total_files = len(files)
    passed = 0
    failed = 0
    all_errors: list[tuple[Path, list[str]]] = []

    for file_path in files:
        is_valid, errors = validate_file(file_path)
        if is_valid:
            passed += 1
            print(f"  [PASS] {file_path}")
        else:
            failed += 1
            print(f"  [FAIL] {file_path}")
            for err in errors:
                print(f"         - {err}")
            all_errors.append((file_path, errors))

    print()
    print("=" * 50)
    print(f"Total: {total_files} | Passed: {passed} | Failed: {failed}")

    if failed > 0:
        print()
        print("Errors by file:")
        for file_path, errors in all_errors:
            print(f"\n  {file_path} ({len(errors)} error(s)):")
            for err in errors:
                print(f"    - {err}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
