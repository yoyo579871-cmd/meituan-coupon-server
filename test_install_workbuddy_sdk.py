"""Offline checks for the pinned SDK's archive and file integrity boundaries."""
import io
import tarfile
import unittest
from unittest.mock import patch

import install_workbuddy_sdk as installer


class InstallerTests(unittest.TestCase):
    def make_archive(self, contents=None, symlink=False):
        contents = contents if contents is not None else {"cliguard.js": b"fake-sdk"}
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, data in contents.items():
                member = tarfile.TarInfo("./scripts/vendor/cliguard/js/" + name)
                if symlink:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "../../../../private-file"
                    archive.addfile(member)
                else:
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        return stream.getvalue()

    def test_archive_checksum_is_checked_before_parsing(self):
        with patch.object(installer.tarfile, "open") as open_archive:
            with self.assertRaisesRegex(ValueError, "bundle changed"):
                installer.extract_verified_files(b"corrupt-archive")
        open_archive.assert_not_called()

    def test_only_allowlisted_files_are_returned_after_checksums_match(self):
        archive = self.make_archive({"cliguard.js": b"fake-sdk", "unused.js": b"unused"})
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"fake-sdk")}):
            self.assertEqual(installer.extract_verified_files(archive),
                             {"cliguard.js": b"fake-sdk"})

    def test_file_checksum_is_checked_even_with_matching_archive_checksum(self):
        archive = self.make_archive()
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"other-sdk")}):
            with self.assertRaisesRegex(ValueError, "file checksum mismatch"):
                installer.extract_verified_files(archive)

    def test_symlink_is_rejected_without_following_its_target(self):
        archive = self.make_archive(symlink=True)
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"fake-sdk")}):
            with self.assertRaisesRegex(ValueError, "Unexpected SDK archive entry"):
                installer.extract_verified_files(archive)

    def test_oversized_file_is_rejected_before_extraction(self):
        archive = self.make_archive({"cliguard.js": b"x" * (1024 * 1024 + 1)})
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": "unused"}), \
                patch.object(tarfile.TarFile, "extractfile") as extract_file:
            with self.assertRaisesRegex(ValueError, "Unexpected SDK archive entry"):
                installer.extract_verified_files(archive)
        extract_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
