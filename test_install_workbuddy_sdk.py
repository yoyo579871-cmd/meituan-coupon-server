"""Offline checks for the pinned SDK's archive and file integrity boundaries."""
import io
import gzip
from pathlib import Path
import tarfile
import tempfile
import unittest
import urllib.error
from unittest.mock import call, patch

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

    def test_repacked_identical_tar_accepts_existing_pinned_files(self):
        original = self.make_archive()
        raw = gzip.decompress(original)
        repacked = gzip.compress(raw, mtime=1)
        self.assertNotEqual(installer.digest(original), installer.digest(repacked))
        self.assertEqual(gzip.decompress(repacked), raw)
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(original)), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"fake-sdk")}):
            self.assertEqual(installer.extract_verified_files(repacked), {"cliguard.js": b"fake-sdk"})

    def test_only_allowlisted_files_are_returned_after_checksums_match(self):
        archive = self.make_archive({"cliguard.js": b"fake-sdk", "unused.js": b"unused"})
        with patch.object(installer, "ARCHIVE_SHA256", "old-bundle-digest"), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"fake-sdk")}):
            self.assertEqual(installer.extract_verified_files(archive),
                             {"cliguard.js": b"fake-sdk"})

    def test_file_checksum_is_checked_even_with_matching_archive_checksum(self):
        archive = self.make_archive()
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"other-sdk")}):
            with self.assertRaisesRegex(installer.SDKInstallError, "sdk_file_checksum_mismatch"):
                installer.extract_verified_files(archive)

    def test_symlink_is_rejected_without_following_its_target(self):
        archive = self.make_archive(symlink=True)
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"fake-sdk")}):
            with self.assertRaisesRegex(installer.SDKInstallError, "unexpected_sdk_entry"):
                installer.extract_verified_files(archive)

    def test_oversized_file_is_rejected_before_extraction(self):
        archive = self.make_archive({"cliguard.js": b"x" * (1024 * 1024 + 1)})
        with patch.object(installer, "ARCHIVE_SHA256", installer.digest(archive)), \
                patch.object(installer, "FILES", {"cliguard.js": "unused"}), \
                patch.object(tarfile.TarFile, "extractfile") as extract_file:
            with self.assertRaisesRegex(installer.SDKInstallError, "unexpected_sdk_entry"):
                installer.extract_verified_files(archive)
        extract_file.assert_not_called()

    def test_missing_and_duplicate_files_are_rejected(self):
        missing = self.make_archive({"other.js": b"fake-sdk"})
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for prefix in ("./", ""):
                member = tarfile.TarInfo(prefix + "scripts/vendor/cliguard/js/cliguard.js")
                member.size = len(b"fake-sdk")
                archive.addfile(member, io.BytesIO(b"fake-sdk"))
        for archive in (missing, stream.getvalue()):
            with self.subTest(archive_size=len(archive)):
                with patch.object(installer, "FILES", {"cliguard.js": installer.digest(b"fake-sdk")}):
                    with self.assertRaisesRegex(installer.SDKInstallError, "missing_or_duplicate_sdk_file"):
                        installer.extract_verified_files(archive)

    def test_compressed_and_unpacked_size_limits_apply_before_tar_parsing(self):
        with patch.object(installer, "MAX_ARCHIVE_BYTES", 32), \
                patch.object(installer.gzip, "GzipFile") as decompress:
            with self.assertRaisesRegex(installer.SDKInstallError, "archive_size_limit"):
                installer.extract_verified_files(b"x" * 33)
        decompress.assert_not_called()
        with patch.object(installer, "MAX_UNPACKED_BYTES", 64), \
                patch.object(installer.tarfile, "open") as open_archive:
            with self.assertRaisesRegex(installer.SDKInstallError, "unpacked_size_limit"):
                installer.extract_verified_files(gzip.compress(b"x" * 1024))
        open_archive.assert_not_called()

    def test_invalid_and_truncated_gzip_is_rejected_before_tar_parsing(self):
        for archive in (b"not-gzip", self.make_archive()[:-8]):
            with self.subTest(archive_size=len(archive)):
                with patch.object(installer.tarfile, "open") as open_archive:
                    with self.assertRaisesRegex(installer.SDKInstallError, "invalid_archive_compression"):
                        installer.extract_verified_files(archive)
                open_archive.assert_not_called()

    def test_second_file_checksum_failure_writes_nothing_and_does_not_redownload(self):
        archive = self.make_archive({"cliguard.js": b"fake-sdk", "package.json": b"changed-package"})
        pins = {"cliguard.js": installer.digest(b"fake-sdk"),
                "package.json": installer.digest(b"approved-package")}
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "sdk"
            with patch.object(installer, "FILES", pins), \
                    patch.object(installer, "DESTINATION", destination), \
                    patch.object(installer, "download_archive", return_value=archive) as download:
                with self.assertRaisesRegex(installer.SDKInstallError, "sdk_file_checksum_mismatch"):
                    installer.main()
            self.assertFalse(destination.exists())
            download.assert_called_once_with()


class DownloadTests(unittest.TestCase):
    def test_two_transient_errors_then_success_uses_bounded_backoff(self):
        error = urllib.error.HTTPError(installer.URL, 503, "private-text", {}, None)
        with patch.object(installer.urllib.request, "urlopen", side_effect=[
                urllib.error.URLError("private-text"), error, io.BytesIO(b"bundle")]) as request, \
                patch.object(installer.time, "sleep") as sleep, patch("builtins.print"):
            self.assertEqual(installer.download_archive(), b"bundle")
        self.assertEqual(request.call_args_list, [call(installer.URL, timeout=30)] * 3)
        self.assertEqual(sleep.call_args_list, [call(2), call(4)])

    def test_retryable_failures_stop_after_three_attempts_without_raw_details(self):
        failures = [urllib.error.URLError("private-text"), TimeoutError("private-text")]
        failures += [urllib.error.HTTPError(installer.URL, code, "private-text", {}, None)
                     for code in (408, 429, 500)]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__, code=getattr(failure, "code", None)):
                with patch.object(installer.urllib.request, "urlopen", side_effect=failure) as request, \
                        patch.object(installer.time, "sleep") as sleep, patch("builtins.print") as output:
                    with self.assertRaises(installer.SDKInstallError) as raised:
                        installer.download_archive()
                self.assertEqual(request.call_count, 3)
                self.assertEqual(sleep.call_args_list, [call(2), call(4)])
                self.assertNotIn("private-text", str(raised.exception) + str(output.call_args_list))

    def test_nonretryable_http_error_and_size_limit_stop_without_retry(self):
        failure = urllib.error.HTTPError(installer.URL, 404, "private-text", {}, None)
        with patch.object(installer.urllib.request, "urlopen", side_effect=failure) as request, \
                patch.object(installer.time, "sleep") as sleep:
            with self.assertRaisesRegex(installer.SDKInstallError, "download_http_404"):
                installer.download_archive()
        request.assert_called_once_with(installer.URL, timeout=30)
        sleep.assert_not_called()
        with patch.object(installer, "MAX_ARCHIVE_BYTES", 32), \
                patch.object(installer.urllib.request, "urlopen", return_value=io.BytesIO(b"x" * 33)) as request, \
                patch.object(installer.time, "sleep") as sleep:
            with self.assertRaisesRegex(installer.SDKInstallError, "archive_size_limit"):
                installer.download_archive()
        request.assert_called_once_with(installer.URL, timeout=30)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
