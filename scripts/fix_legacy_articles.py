#!/usr/bin/env python3
"""批量修复历史文章的 ID 和 status 格式。"""

import json
import re
from pathlib import Path

ARTICLES_DIR = Path("knowledge/articles")
OLD_ID_PATTERN = re.compile(r"^github-trending-20260517-[a-f0-9]{8}$")


def fix_file(filepath: Path, seq: int) -> bool:
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        return False

    modified = False

    # 修复 ID
    old_id = data.get("id", "")
    if OLD_ID_PATTERN.match(old_id):
        data["id"] = f"github-trending-20260517-{seq:03d}"
        modified = True

    # 修复 status
    if data.get("status") == "pending":
        data["status"] = "draft"
        modified = True

    if modified:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return modified


def main() -> None:
    files = sorted(ARTICLES_DIR.glob("github_trending_20260517_*.json"))
    fixed = 0

    for i, filepath in enumerate(files, start=1):
        if fix_file(filepath, i):
            print(f"  [FIXED] {filepath.name} -> id=github-trending-20260517-{i:03d}, status=draft")
            fixed += 1
        else:
            print(f"  [SKIP]  {filepath.name}")

    print(f"\n总计: {len(files)} 文件 | 修复: {fixed}")


if __name__ == "__main__":
    main()
