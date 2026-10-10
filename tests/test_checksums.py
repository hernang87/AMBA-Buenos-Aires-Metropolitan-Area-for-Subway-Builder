import hashlib
import io
import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts import checksums
from scripts.checksums import ChecksumError


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FakeOpener:
    def __init__(self, data: bytes):
        self.data = data
        self.calls = 0

    def __call__(self, request, timeout=None):
        self.calls += 1
        return io.BytesIO(self.data)


class ChecksumDownloadTests(unittest.TestCase):
    KEY = "data/raw/sample.csv"
    URL = "https://example.invalid/sample.csv"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.checksums_path = self.root / "data/checksums.json"
        self.checksums_path.parent.mkdir(parents=True)
        self.dest = self.root / self.KEY
        self.dest.parent.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self.tmp.cleanup()

    def write_entry(self, policy, sha256):
        entries = {
            self.KEY: {"policy": policy, "sha256": sha256, "retrieved": None},
        }
        checksums.save_checksums(entries, self.checksums_path)

    def run_download(self, opener, **kwargs):
        return checksums.download(
            self.URL,
            self.dest,
            user_agent="test-agent",
            checksums_path=self.checksums_path,
            root=self.root,
            opener=opener,
            **kwargs,
        )

    def stored_entry(self):
        return checksums.load_checksums(self.checksums_path)[self.KEY]

    def test_pinned_match_skips_without_opening(self):
        data = b"pinned content"
        self.dest.write_bytes(data)
        self.write_entry("pinned", sha(data))
        opener = FakeOpener(b"other")

        self.assertEqual(self.run_download(opener), "skipped")
        self.assertEqual(opener.calls, 0)
        self.assertEqual(self.dest.read_bytes(), data)

    def test_pinned_mismatch_raises_and_leaves_dest_untouched(self):
        self.dest.write_bytes(b"old content")
        self.write_entry("pinned", sha(b"expected content"))
        opener = FakeOpener(b"new upstream content")

        with self.assertRaises(ChecksumError):
            self.run_download(opener)
        self.assertEqual(self.dest.read_bytes(), b"old content")
        self.assertFalse(self.dest.with_name(self.dest.name + ".part").exists())

    def test_record_null_hash_records_existing_file(self):
        data = b"existing rows"
        self.dest.write_bytes(data)
        self.write_entry("record", None)
        opener = FakeOpener(b"unused")

        self.assertEqual(self.run_download(opener), "recorded")
        self.assertEqual(opener.calls, 0)
        entry = self.stored_entry()
        self.assertEqual(entry["sha256"], sha(data))
        self.assertEqual(entry["retrieved"], date.today().isoformat())

    def test_record_null_hash_accepts_download_when_missing(self):
        data = b"fresh rows"
        self.write_entry("record", None)
        opener = FakeOpener(data)

        self.assertEqual(self.run_download(opener), "downloaded")
        self.assertEqual(opener.calls, 1)
        self.assertEqual(self.dest.read_bytes(), data)
        self.assertEqual(self.stored_entry()["sha256"], sha(data))

    def test_record_mismatch_raises_then_update_rewrites_hash(self):
        self.dest.write_bytes(b"local copy")
        self.write_entry("record", sha(b"previously recorded"))
        new_data = b"changed upstream"

        with self.assertRaises(ChecksumError):
            self.run_download(FakeOpener(new_data))
        self.assertEqual(self.dest.read_bytes(), b"local copy")
        self.assertFalse(self.dest.with_name(self.dest.name + ".part").exists())

        self.assertEqual(self.run_download(FakeOpener(new_data), update=True), "downloaded")
        self.assertEqual(self.dest.read_bytes(), new_data)
        self.assertEqual(self.stored_entry()["sha256"], sha(new_data))

    def test_volatile_existing_file_is_kept_without_opening(self):
        self.dest.write_bytes(b"kept content")
        self.write_entry("volatile", None)
        opener = FakeOpener(b"unused")

        self.assertEqual(self.run_download(opener), "kept")
        self.assertEqual(opener.calls, 0)
        self.assertEqual(self.dest.read_bytes(), b"kept content")

    def test_unlisted_key_raises(self):
        other = self.root / "data/raw/unlisted.csv"
        self.write_entry("record", None)
        with self.assertRaises(ChecksumError):
            checksums.download(
                self.URL,
                other,
                user_agent="test-agent",
                checksums_path=self.checksums_path,
                root=self.root,
                opener=FakeOpener(b"data"),
            )

    def test_file_status_reports_all_statuses(self):
        data = b"status content"
        path = self.dest
        if path.exists():
            path.unlink()

        self.assertEqual(checksums.file_status(path, {"policy": "record", "sha256": None}), "missing")

        path.write_bytes(data)
        self.assertEqual(checksums.file_status(path, {"policy": "record", "sha256": None}), "unrecorded")
        self.assertEqual(checksums.file_status(path, {"policy": "record", "sha256": sha(data)}), "match")
        self.assertEqual(checksums.file_status(path, {"policy": "pinned", "sha256": sha(b"x")}), "mismatch")
        self.assertEqual(checksums.file_status(path, {"policy": "volatile", "sha256": sha(b"x")}), "changed")


if __name__ == "__main__":
    unittest.main()
