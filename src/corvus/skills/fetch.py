"""Fetch and verify skill packages from allowlisted sources."""

from __future__ import annotations

import hashlib
import io
import os
import shutil
import tarfile
import tempfile
import zipfile
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

from corvus.skills.netguard import assert_safe_http_url, parse_allowlist


def skill_source_allowlist() -> list[str]:
    return parse_allowlist(os.environ.get("CORVUS_SKILL_SOURCE_ALLOWLIST", ""))


def assert_source_allowed(source: str) -> None:
    allow = skill_source_allowlist()
    if source.startswith("file:"):
        # Local file installs always allowed for operator/dev (still hashed).
        return
    assert_safe_http_url(
        source,
        allow,
        empty_message=(
            "remote skill install denied: set CORVUS_SKILL_SOURCE_ALLOWLIST "
            "to comma-separated URL prefixes"
        ),
    )


def _download_bytes(source: str) -> bytes:
    assert_source_allowed(source)
    parsed = urlparse(source)
    if parsed.scheme == "file":
        path = Path(parsed.path)
        if not path.is_file():
            raise ValueError(f"file source not found: {path}")
        return path.read_bytes()
    if parsed.scheme in {"http", "https"}:
        with urlopen(source, timeout=30) as resp:  # noqa: S310 — allowlist gated
            return resp.read()
    raise ValueError(f"unsupported source scheme: {parsed.scheme or 'none'}")


def fetch_and_extract(
    source: str,
    *,
    pin: str,
    sha256: str,
    dest: Path,
    skill_id: str | None = None,
) -> Path:
    """Download package, verify sha256, extract into dest. Returns skill root dir."""
    if not pin or pin.lower() == "latest":
        raise ValueError("floating pin 'latest' is not allowed")
    if not sha256 or len(sha256) < 32:
        raise ValueError("sha256 is required")
    blob = _download_bytes(source)
    digest = hashlib.sha256(blob).hexdigest()
    if digest.lower() != sha256.lower():
        raise ValueError(f"sha256 mismatch: expected {sha256}, got {digest}")

    dest.mkdir(parents=True, exist_ok=True)
    extract_root = dest / "extract"
    if extract_root.exists():
        shutil.rmtree(extract_root)
    extract_root.mkdir(parents=True)

    if zipfile.is_zipfile(io.BytesIO(blob)):
        with zipfile.ZipFile(io.BytesIO(blob)) as zf:
            _safe_extract_zip(zf, extract_root)
    else:
        try:
            with tarfile.open(fileobj=io.BytesIO(blob), mode="r:*") as tf:
                _safe_extract_tar(tf, extract_root)
        except tarfile.TarError as exc:
            raise ValueError("package is not a valid zip or tar archive") from exc

    return _find_skill_root(extract_root, skill_id=skill_id)


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    for info in zf.infolist():
        name = info.filename
        if name.endswith("/"):
            continue
        target = (dest / name).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise ValueError(f"zip slip denied: {name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out)


def _safe_extract_tar(tf: tarfile.TarFile, dest: Path) -> None:
    for member in tf.getmembers():
        if not member.isfile():
            if member.issym() or member.islnk():
                raise ValueError("tar links denied")
            continue
        target = (dest / member.name).resolve()
        if not str(target).startswith(str(dest.resolve())):
            raise ValueError(f"tar slip denied: {member.name}")
        target.parent.mkdir(parents=True, exist_ok=True)
        src = tf.extractfile(member)
        if src is None:
            continue
        with src, target.open("wb") as out:
            shutil.copyfileobj(src, out)


def _find_skill_root(extract_root: Path, *, skill_id: str | None = None) -> Path:
    if skill_id:
        # Bound walk: GitHub archives nest under owner-repo-sha/; skills may be deeper.
        matches: list[Path] = []
        for path in extract_root.rglob("SKILL.md"):
            if not path.is_file():
                continue
            if path.parent.name == skill_id:
                matches.append(path.parent)
            if len(matches) > 20:
                break
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise ValueError(f"multiple skill directories named {skill_id!r} in archive")
        raise ValueError(f"skill {skill_id!r} with SKILL.md not found in archive")

    direct = extract_root / "SKILL.md"
    if direct.is_file():
        return extract_root
    candidates = [p for p in extract_root.iterdir() if p.is_dir()]
    for cand in candidates:
        if (cand / "SKILL.md").is_file():
            return cand
    raise ValueError("archive must contain SKILL.md at root or one level down")


def staging_dir() -> Path:
    return Path(tempfile.mkdtemp(prefix="corvus-skill-"))
