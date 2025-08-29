"""
Remove specific "test" screenshots and prune empty athlete/team folders.
"""

from pathlib import Path
import argparse
from typing import Iterable, List, Optional, Callable
import os

TARGET_FILENAMES = [
    "Countermovement_Jump_001.png",
    "20yd_Sprint_001.png",
    "5-0-5_Drill_001.png",
    "Nordic_001.png",
]

VALID_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}

# Global logger callback
LOGGER_CALLBACK: Optional[Callable[[str, str], None]] = None

def set_logger_callback(callback: Optional[Callable[[str, str], None]]) -> None:
    """Sets a global callback for logging."""
    global LOGGER_CALLBACK
    LOGGER_CALLBACK = callback

def log(tag: str, msg: str) -> None:
    if LOGGER_CALLBACK:
        LOGGER_CALLBACK(tag, msg)
    else:
        print(f"[{tag.upper()}] {msg}")

def iter_team_dirs(root: Path) -> Iterable[Path]:
    """Yield team directories directly under the root."""
    for child in root.iterdir():
        if child.is_dir():
            yield child


def iter_athlete_dirs(team_dir: Path) -> Iterable[Path]:
    """Yield athlete directories directly under a team directory."""
    for child in team_dir.iterdir():
        if child.is_dir():
            yield child


def is_dir_completely_empty(p: Path) -> bool:
    """True if directory has zero entries (no files, no subfolders)."""
    try:
        next(p.iterdir())
        return False
    except StopIteration:
        return True


def delete_targets_in_athlete_dir(athlete_dir: Path, dry_run: bool = False) -> int:
    """Delete target files in a single athlete folder. Returns count deleted."""
    deleted_here = 0
    for filename in TARGET_FILENAMES:
        path = athlete_dir / filename
        try:
            if path.exists():
                if dry_run:
                    log("dry", f"Would delete: {path}")
                else:
                    path.unlink()
                    log("del", f"{path}")
                deleted_here += 1
        except PermissionError:
            log("skip", f"Permission denied: {path}")
        except Exception as e:
            log("skip", f"{path} -> {e}")
    return deleted_here


def folder_directly_contains_images(folder: Path) -> bool:
    """Heuristic to detect athlete folders directly under root (back-compat)."""
    try:
        for name in os.listdir(folder):
            p = folder / name
            if p.is_file() and p.suffix.lower() in VALID_IMAGE_EXTS:
                return True
    except Exception:
        pass
    return False


def run_cleanup(
    root: Path,
    teams_filter: List[str],
    dry_run: bool,
    prune_empty_teams: bool,
    log_callback: Optional[Callable[[str, str], None]] = None,
) -> bool:
    """Scan root/team/athlete and remove target files + prune empty folders."""
    if log_callback:
        set_logger_callback(log_callback)

    if not root.exists() or not root.is_dir():
        log("err", f"Root does not exist or is not a directory: {root}")
        return False

    teams_filter_norm = (
        {t.strip().lower() for t in teams_filter if t.strip()}
        if teams_filter
        else set()
    )

    teams_seen = 0
    athletes_seen = 0
    files_deleted = 0
    athlete_dirs_removed = 0
    team_dirs_removed = 0

    # ---------- Team -> Athlete structure ----------
    for team_dir in iter_team_dirs(root):
        team_name = team_dir.name
        if folder_directly_contains_images(team_dir):
            continue

        if teams_filter_norm and team_name.lower() not in teams_filter_norm:
            continue

        log("team", f"{team_name}")
        teams_seen += 1

        for athlete_dir in iter_athlete_dirs(team_dir):
            athletes_seen += 1
            files_deleted += delete_targets_in_athlete_dir(athlete_dir, dry_run=dry_run)
            try:
                if is_dir_completely_empty(athlete_dir):
                    if dry_run:
                        log("dry", f"Would remove empty athlete folder: {athlete_dir}")
                    else:
                        athlete_dir.rmdir()
                        log("del", f"{athlete_dir}")
                    athlete_dirs_removed += 1
                else:
                    log("keep", f"{athlete_dir} (not empty)")
            except PermissionError:
                log("skip", f"Permission denied: {athlete_dir}")
            except Exception as e:
                log("skip", f"{athlete_dir} -> {e}")

        if prune_empty_teams:
            try:
                if is_dir_completely_empty(team_dir):
                    if dry_run:
                        log("dry", f"Would remove empty team folder: {team_dir}")
                    else:
                        team_dir.rmdir()
                        log("del", f"{team_dir}")
                    team_dirs_removed += 1
            except PermissionError:
                log("skip", f"Permission denied (team): {team_dir}")
            except Exception as e:
                log("skip", f"{team_dir} -> {e}")

    # ---------- Back-compat: athletes directly under root ----------
    direct_athletes = [
        p for p in root.iterdir() if p.is_dir() and folder_directly_contains_images(p)
    ]
    if direct_athletes:
        log(
            "info", "Also scanning athlete folders directly under root (back-compat)."
        )
    for athlete_dir in direct_athletes:
        athletes_seen += 1
        files_deleted += delete_targets_in_athlete_dir(athlete_dir, dry_run=dry_run)
        try:
            if is_dir_completely_empty(athlete_dir):
                if dry_run:
                    log("dry", f"Would remove empty athlete folder: {athlete_dir}")
                else:
                    athlete_dir.rmdir()
                    log("del", f"{athlete_dir}")
                athlete_dirs_removed += 1
            else:
                log("keep", f"{athlete_dir} (not empty)")
        except PermissionError:
            log("skip", f"Permission denied: {athlete_dir}")
        except Exception as e:
            log("skip", f"{athlete_dir} -> {e}")

    # ---------- Summary ----------
    summary_msg = (
        f"Teams scanned: {teams_seen} | Athlete folders checked: {athletes_seen} | "
        f"Files {'to be deleted' if dry_run else 'deleted'}: {files_deleted} | "
        f"Athlete folders {'to be removed' if dry_run else 'removed'}: {athlete_dirs_removed}"
        + (
            f" | Team folders {'to be removed' if dry_run else 'removed'}: {team_dirs_removed}"
            if prune_empty_teams
            else ""
        )
    )
    log("info", summary_msg)
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Delete VALD 'test' screenshots and remove COMPLETELY EMPTY athlete/team folders."
    )
    parser.add_argument(
        "--root",
        type=str,
        default=r"D:\Vald Data",
        help='Root directory containing team folders (default: "D:\\Vald Data")',
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be deleted without actually deleting.",
    )
    parser.add_argument(
        "--teams",
        type=str,
        default="",
        help="Comma-separated list of team names to limit the cleanup (exact match).",
    )
    parser.add_argument(
        "--prune-empty-teams",
        action="store_true",
        help="Also remove a team folder if it ends up completely empty.",
    )
    args = parser.parse_args()

    teams_filter = [t.strip() for t in args.teams.split(",")] if args.teams else []
    run_cleanup(
        Path(args.root),
        teams_filter=teams_filter,
        dry_run=args.dry_run,
        prune_empty_teams=args.prune_empty_teams,
    )


if __name__ == "__main__":
    main()
