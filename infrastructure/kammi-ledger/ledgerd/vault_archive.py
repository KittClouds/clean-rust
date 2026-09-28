"""Bounded ZIP64 transport for portable vault packages."""
from __future__ import annotations

import os
import re
import shutil
import zipfile
from pathlib import Path

MAX_PACKAGE_BYTES = 64 * 1024 * 1024 * 1024
MAX_PACKAGE_FILES = 100_000
OBJECT_NAME = re.compile(r"objects/sha256/[0-9a-f]{2}/[0-9a-f]{62}\Z")


def pack(directory: Path, archive: Path) -> None:
    with zipfile.ZipFile(archive, "w", allowZip64=True,
                         compression=zipfile.ZIP_STORED) as output:
        for path in sorted(directory.rglob("*")):
            if path.is_symlink():
                raise ValueError("vault package cannot contain symlinks")
            if path.is_file():
                output.write(path, path.relative_to(directory).as_posix())


def unpack(archive: Path, destination: Path) -> None:
    total, names = 0, set()
    with zipfile.ZipFile(archive, "r", allowZip64=True) as source:
        members = source.infolist()
        if len(members) > MAX_PACKAGE_FILES:
            raise ValueError("vault package has too many objects")
        for member in members:
            name = member.filename
            if name in names or (name != "VAULT.json" and not OBJECT_NAME.fullmatch(name)):
                raise ValueError("vault package contains duplicate or unsafe path")
            names.add(name)
            if member.is_dir() or member.file_size > MAX_PACKAGE_BYTES:
                raise ValueError("vault package object exceeds limit")
            total += member.file_size
            if total > MAX_PACKAGE_BYTES:
                raise ValueError("vault package exceeds limit")
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(member, "r") as src, target.open("xb") as dst:
                shutil.copyfileobj(src, dst, 1024 * 1024)
                dst.flush()
                os.fsync(dst.fileno())
    if "VAULT.json" not in names:
        raise ValueError("vault package manifest missing")
