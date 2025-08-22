"""
Remove specific "test" screenshots from every athlete folder under a VALD data root.

Defaults to D:/Vald Data but allows overriding with --root.

Deletes ONLY these files if present inside each athlete folder:
- Countermovement_Jump_001.png
- 20yd_Sprint_001.png
- 5-0-5_Drill_001.png
- Nordic_001.png
"""

from pathlib import Path
import argparse

TARGET_FILENAMES = [
    "Countermovement_Jump_001.png",
    "20yd_Sprint_001.png",
    "5-0-5_Drill_001.png",
    "Nordic_001.png",
]


def remove_targets(root: Path) -> None:
    if not root.exists() or not root.is_dir():
        print(f"[ERR] Root does not exist or is not a directory: {root}")
        return

    total_deleted = 0
    folders_seen = 0

    for child in root.iterdir():
        if not child.is_dir():
            continue
        folders_seen += 1
        deleted_here = 0

        for filename in TARGET_FILENAMES:
            path = child / filename
            try:
                if path.exists():
                    path.unlink()
                    print(f"[DEL] {path}")
                    total_deleted += 1
                    deleted_here += 1
            except PermissionError:
                print(f"[SKIP] Permission denied: {path}")
            except Exception as e:
                print(f"[SKIP] {path} -> {e}")

        if deleted_here == 0:
            # Quiet by default, but you can uncomment next line if you want per-folder status.
            # print(f"[OK ] No targets in: {child.name}")
            pass

    print(f"\nDone. Folders scanned: {folders_seen} | Files deleted: {total_deleted}")


def main():
    parser = argparse.ArgumentParser(
        description="Clean VALD test screenshots per athlete folder."
    )
    parser.add_argument(
        "--root",
        type=str,
        default=r"D:\Vald Data",
        help='Root directory containing athlete folders (default: "D:\\Vald Data")',
    )
    args = parser.parse_args()
    remove_targets(Path(args.root))


if __name__ == "__main__":
    main()
