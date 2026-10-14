"""The only module that opens files in the Reflex folder (SR-08, ARCHITECTURE section 10).

- The root is resolved with realpath(strict=True).
- Only the FR-40 folders are listed, with os.scandir. Symlinks, junctions and
  reparse points are refused.
- File names must match an FR-40 pattern, and the SR-08 deny rules apply before
  any open.
- After the open, os.fstat must agree with the earlier stat (same file).
"""

import fnmatch
import os
import re
import stat
from pathlib import Path

PATTERNS = {
    "dashboard": ["*_reflex_dashboard.json"],
    "ToDo": ["*_Action_Items_Report*.docx", "*_Monday_Update.docx", "*_Marlow_Monday_Update_Section*.md"],
    "Notes": ["*_Weekly_Priorities.docx", "*_Day_Plan.docx"],
    "Dashboards": ["*_reflex_platform_usage_dashboard.html"],
}
DENY_DIRS = {"benefits", "paystubs"}
DENY_NAME = re.compile(r"w9|invoice|agreement", re.IGNORECASE)
DATED = re.compile(r"^\d{4}-\d{2}-\d{2}_")
REPARSE =getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class Refused(Exception):
    pass


def _bad_entry(st: os.stat_result) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & REPARSE)


class ReflexGuard:
    def __init__(self, root: Path):
        self.root = Path(os.path.realpath(root, strict=True))

    def files(self, folder: str, pattern: str) -> list[tuple[str, os.stat_result]]:
        """(name, stat) of the files in one FR-40 folder that match one FR-40 pattern."""
        if folder not in PATTERNS or pattern not in PATTERNS[folder] or folder.lower() in DENY_DIRS:
            raise Refused(f"not an FR-40 folder or pattern: {folder}/{pattern}")
        d = self.root / folder
        try:
            dst = os.stat(d, follow_symlinks=False)
        except FileNotFoundError:
            return []
        if _bad_entry(dst) or not stat.S_ISDIR(dst.st_mode):
            raise Refused(f"{folder} is a link or not a folder")
        out = []
        with os.scandir(d) as it:
            for e in it:
                if DENY_NAME.search(e.name) or not fnmatch.fnmatch(e.name, pattern):
                    continue
                if not DATED.match(e.name):  # also skips Word lock files (~$...)
                    continue
                # full stat: DirEntry.stat() on Windows has no inode number
                st = os.stat(e.path, follow_symlinks=False)
                if _bad_entry(st) or not stat.S_ISREG(st.st_mode):
                    continue
                out.append((e.name, st))
        return out

    def newest(self, folder: str, pattern: str) -> tuple[str, os.stat_result] | None:
        """Newest by the date at the start of the name; _refreshed wins on the same date (FR-42)."""
        files = self.files(folder, pattern)
        if not files:
            return None
        return max(files, key=lambda f: (f[0][:10], "_refreshed" in f[0]))

    def open(self, folder: str, name: str, st: os.stat_result):
        """Open a file that files() returned, read-only, and check that it is the same file."""
        if DENY_NAME.search(name) or "/" in name or "\\" in name or name in (".", ".."):
            raise Refused(f"refused name {name}")
        path = self.root / folder / name
        f = open(path, "rb")
        try:
            now = os.fstat(f.fileno())
            if (now.st_ino, now.st_dev, now.st_size) != (st.st_ino, st.st_dev, st.st_size):
                raise Refused(f"{name} changed between the check and the open")
        except Exception:
            f.close()
            raise
        return f
