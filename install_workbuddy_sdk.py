#!/usr/bin/env python3
"""Fetch only the pinned client signing files from the WorkBuddy distribution.

No local account files or device identifiers are uploaded or bundled in git.
Archive extraction uses an exact file allowlist, never extractall().
"""
import hashlib
import io
from pathlib import Path
import sys
import tarfile
import urllib.request

URL = "https://acc-1258344699.cos.accelerate.myqcloud.com/workbuddy/expert-marketplace/bundles/meituan-living-assistant.tar.gz"
ARCHIVE_SHA256 = "ec9e9d2e2758ae7fdfff2b1ffc454bc9b8e2ef153989fb6f68d34e8bfa24e07b"
FILES = {
    "cliguard.js": "eff1a324fdec2201ef021da00d02e64324cbf59e1328966718e4a43c6b6626cf",
    "package.json": "99f781a091ab69ef851a7a20802d413092171e94333603a6953afaaf5a7aeeff",
}
DESTINATION = Path(__file__).parent / ".runtime" / "cliguard"
MAX_ARCHIVE_BYTES = 10 * 1024 * 1024


def digest(value):
    return hashlib.sha256(value).hexdigest()


def extract_verified_files(archive):
    if digest(archive) != ARCHIVE_SHA256:
        raise ValueError("WorkBuddy bundle changed; review its checksum before updating")
    content = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as bundle:
        for name, expected in FILES.items():
            member = bundle.getmember("./scripts/vendor/cliguard/js/" + name)
            if not member.isfile() or member.size > 1024 * 1024:
                raise ValueError("Unexpected SDK archive entry")
            data = bundle.extractfile(member).read()
            if digest(data) != expected:
                raise ValueError("SDK file checksum mismatch")
            content[name] = data
    return content


def main():
    if all((DESTINATION / name).is_file()
           and digest((DESTINATION / name).read_bytes()) == expected
           for name, expected in FILES.items()):
        print("[SDK] Verified cached CLIGuard 1.3.1")
        return 0
    with urllib.request.urlopen(URL, timeout=60) as response:
        archive = response.read(MAX_ARCHIVE_BYTES + 1)
    if len(archive) > MAX_ARCHIVE_BYTES:
        raise ValueError("SDK archive exceeds size limit")
    content = extract_verified_files(archive)
    DESTINATION.mkdir(parents=True, exist_ok=True)
    for name, data in content.items():
        (DESTINATION / name).write_bytes(data)
    print("[SDK] Installed and verified CLIGuard 1.3.1 from WorkBuddy bundle")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, tarfile.TarError):
        print("[FAIL] SDK download or integrity verification failed; claiming must not continue")
        sys.exit(1)
