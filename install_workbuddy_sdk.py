#!/usr/bin/env python3
"""Fetch only the pinned client signing files from the WorkBuddy distribution.

No local account files or device identifiers are uploaded or bundled in git.
Archive extraction uses an exact file allowlist, never extractall().
"""
import hashlib
import gzip
import io
from pathlib import Path
import sys
import tarfile
import time
import urllib.error
import urllib.request

URL = "https://acc-1258344699.cos.accelerate.myqcloud.com/workbuddy/expert-marketplace/bundles/meituan-living-assistant.tar.gz"
ARCHIVE_SHA256 = "ec9e9d2e2758ae7fdfff2b1ffc454bc9b8e2ef153989fb6f68d34e8bfa24e07b"
FILES = {
    "cliguard.js": "eff1a324fdec2201ef021da00d02e64324cbf59e1328966718e4a43c6b6626cf",
    "package.json": "99f781a091ab69ef851a7a20802d413092171e94333603a6953afaaf5a7aeeff",
}
DESTINATION = Path(__file__).parent / ".runtime" / "cliguard"
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024
MAX_UNPACKED_BYTES = 32 * 1024 * 1024


class SDKInstallError(ValueError):
    """An allowlisted diagnostic that never includes credentials or raw bodies."""


def digest(value):
    return hashlib.sha256(value).hexdigest()


def extract_verified_files(archive):
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise SDKInstallError("archive_size_limit")
    if digest(archive) != ARCHIVE_SHA256:
        # The market bundle can change independently of the signing core.
        # Only the two pinned files below are installed or executed.
        print("[SDK] Bundle archive changed; checking pinned signing files")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(archive)) as compressed:
            unpacked = compressed.read(MAX_UNPACKED_BYTES + 1)
    except (OSError, EOFError):
        raise SDKInstallError("invalid_archive_compression") from None
    if len(unpacked) > MAX_UNPACKED_BYTES:
        raise SDKInstallError("unpacked_size_limit")
    content = {}
    with tarfile.open(fileobj=io.BytesIO(unpacked), mode="r:") as bundle:
        for name, expected in FILES.items():
            matches = [member for member in bundle.getmembers()
                       if member.name in ("./scripts/vendor/cliguard/js/" + name,
                                          "scripts/vendor/cliguard/js/" + name)]
            if len(matches) != 1:
                raise SDKInstallError("missing_or_duplicate_sdk_file: " + name)
            member = matches[0]
            if not member.isfile() or member.size > 1024 * 1024:
                raise SDKInstallError("unexpected_sdk_entry: " + name)
            data = bundle.extractfile(member).read()
            if digest(data) != expected:
                raise SDKInstallError("sdk_file_checksum_mismatch: " + name)
            content[name] = data
    return content


def download_archive():
    # Bounded retries are only for this read-only dependency GET, never claims.
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(URL, timeout=30) as response:
                archive = response.read(MAX_ARCHIVE_BYTES + 1)
            if len(archive) > MAX_ARCHIVE_BYTES:
                raise SDKInstallError("archive_size_limit")
            return archive
        except urllib.error.HTTPError as error:
            reason = "download_http_" + str(error.code)
            transient = error.code in (408, 429) or 500 <= error.code <= 599
        except (urllib.error.URLError, TimeoutError, OSError):
            reason, transient = "download_transport_error", True
        if not transient or attempt == 3:
            raise SDKInstallError(reason) from None
        print(f"[SDK] {reason}; dependency download retry {attempt}/2")
        time.sleep(attempt * 2)


def main():
    if all((DESTINATION / name).is_file()
           and digest((DESTINATION / name).read_bytes()) == expected
           for name, expected in FILES.items()):
        print("[SDK] Verified cached CLIGuard 1.3.1")
        return 0
    archive = download_archive()
    content = extract_verified_files(archive)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name, data in content.items():
        (DESTINATION / name).write_bytes(data)
    print("[SDK] Installed and verified CLIGuard 1.3.1 from WorkBuddy bundle")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SDKInstallError as error:
        print(f"[FAIL] SDK installation: {error}; no claim request sent")
        sys.exit(1)
    except (OSError, ValueError, KeyError, tarfile.TarError):
        print("[FAIL] SDK archive parsing or local file operation failed; no claim request sent")
        sys.exit(1)
