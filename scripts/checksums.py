from __future__ import annotations

import argparse
import hashlib
import json
import os
import urllib.request
from datetime import date
from pathlib import Path
from urllib.request import Request

ROOT = Path(__file__).resolve().parents[1]
CHECKSUMS_PATH = ROOT / "data/checksums.json"
CHUNK_SIZE = 1024 * 1024


class ChecksumError(Exception):
    pass


def user_agent(version: str) -> str:
    return f"BUE-Subway-Builder/{version}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def load_checksums(path: Path = CHECKSUMS_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["files"]


def save_checksums(entries: dict, path: Path = CHECKSUMS_PATH) -> None:
    data = {"files": entries, "version": 1}
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def entry_key(path: Path, root: Path = ROOT) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        raise ChecksumError(f"{path} is outside the repository") from None


def file_status(path: Path, entry: dict) -> str:
    if not path.exists():
        return "missing"
    if entry["sha256"] is None:
        return "unrecorded"
    if sha256_file(path) == entry["sha256"]:
        return "match"
    return "changed" if entry["policy"] == "volatile" else "mismatch"


def download(
    url: str,
    dest: Path,
    *,
    user_agent: str,
    entries: dict | None = None,
    checksums_path: Path = CHECKSUMS_PATH,
    update: bool = False,
    force: bool = False,
    root: Path = ROOT,
    opener=urllib.request.urlopen,
) -> str:
    if entries is None:
        entries = load_checksums(checksums_path)
    key = entry_key(dest, root)
    if key not in entries:
        raise ChecksumError(f"{key} is not listed in data/checksums.json")
    entry = entries[key]
    policy = entry["policy"]

    if dest.exists() and not force:
        if policy == "volatile":
            print(f"Keeping existing {key}")
            return "kept"
        status = file_status(dest, entry)
        if status == "match":
            print(f"Verified {key}, skipping download")
            return "skipped"
        if status == "unrecorded" and policy == "record":
            entry["sha256"] = sha256_file(dest)
            entry["retrieved"] = date.today().isoformat()
            save_checksums(entries, checksums_path)
            return "recorded"

    part = dest.with_name(dest.name + ".part")
    dest.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    try:
        request = Request(url, headers={"User-Agent": user_agent})
        with opener(request, timeout=60) as response, part.open("wb") as handle:
            while chunk := response.read(CHUNK_SIZE):
                digest.update(chunk)
                handle.write(chunk)
        actual = digest.hexdigest()
        expected = entry["sha256"]

        if policy == "pinned":
            if expected is not None and actual != expected and not update:
                raise ChecksumError(
                    f"{key}: sha256 mismatch (expected {expected}, got {actual}); "
                    "rerun with --update to accept"
                )
        elif policy == "record":
            if expected is not None and actual != expected and not update:
                raise ChecksumError(f"{key}: upstream changed; rerun with --update to accept")
        elif policy == "volatile" and expected is not None and actual != expected:
            print(f"Warning: {key} changed upstream")

        os.replace(part, dest)
    except BaseException:
        part.unlink(missing_ok=True)
        raise

    if actual != entry["sha256"]:
        entry["sha256"] = actual
        entry["retrieved"] = date.today().isoformat()
        save_checksums(entries, checksums_path)
    return "downloaded"


def _verify(keys: list[str]) -> int:
    entries = load_checksums()
    if not keys:
        keys = sorted(entries)
    exit_code = 0
    for key in keys:
        if key not in entries:
            raise ChecksumError(f"{key} is not listed in data/checksums.json")
        status = file_status(ROOT / key, entries[key])
        print(f"{status:10} {key}")
        if status == "mismatch":
            exit_code = 1
    return exit_code


def _record(keys: list[str]) -> int:
    entries = load_checksums()
    for key in keys:
        if key not in entries:
            raise ChecksumError(f"{key} is not listed in data/checksums.json")
        path = ROOT / key
        if not path.exists():
            raise ChecksumError(f"{key} does not exist")
        entries[key]["sha256"] = sha256_file(path)
        entries[key]["retrieved"] = date.today().isoformat()
        print(f"Recorded {key}")
    save_checksums(entries)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify or record checksums of raw data inputs.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    verify_parser = subparsers.add_parser("verify", help="Report the status of listed files.")
    verify_parser.add_argument("keys", nargs="*")
    record_parser = subparsers.add_parser("record", help="Record current sha256 of listed files.")
    record_parser.add_argument("keys", nargs="+")
    args = parser.parse_args()

    try:
        if args.command == "verify":
            return _verify(args.keys)
        return _record(args.keys)
    except ChecksumError as error:
        raise SystemExit(str(error))


if __name__ == "__main__":
    raise SystemExit(main())
