"""Browse allowlisted public Agent Skills registries (skills.sh-compatible API)."""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

from corvus.skills.install import InstallRequest, InstallResult, install_skill
from corvus.skills.netguard import assert_safe_http_url, parse_allowlist
from corvus.skills.store import SkillStore

_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_USER_AGENT = "corvus-hypervisor-skill-browser/0.8"


class BrowseDisabledError(ValueError):
    """Registry URL or allowlist not configured."""


@dataclass(frozen=True)
class BrowseSkill:
    id: str
    name: str
    description: str
    owner: str
    repo: str
    installs: int
    source_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "owner": self.owner,
            "repo": self.repo,
            "installs": self.installs,
            "source_url": self.source_url,
        }


def skill_registry_url() -> str:
    return (os.environ.get("CORVUS_SKILL_REGISTRY_URL") or "").strip().rstrip("/")


def skill_registry_allowlist() -> list[str]:
    return parse_allowlist(os.environ.get("CORVUS_SKILL_REGISTRY_ALLOWLIST", ""))


def assert_browse_enabled() -> str:
    base = skill_registry_url()
    if not base:
        raise BrowseDisabledError(
            "skill browser disabled: set CORVUS_SKILL_REGISTRY_URL to a "
            "skills.sh-compatible registry base URL"
        )
    if "://" not in base:
        raise BrowseDisabledError("CORVUS_SKILL_REGISTRY_URL must include http(s)://")
    allow = skill_registry_allowlist()
    if not allow:
        raise BrowseDisabledError(
            "skill browser disabled: set CORVUS_SKILL_REGISTRY_ALLOWLIST "
            "to comma-separated URL prefixes"
        )
    try:
        assert_safe_http_url(
            base,
            allow,
            empty_message=(
                "skill browser disabled: set CORVUS_SKILL_REGISTRY_ALLOWLIST "
                "to comma-separated URL prefixes"
            ),
        )
    except ValueError as exc:
        # Treat misconfig (allowlist / private IP) as disabled for API 503.
        msg = str(exc)
        if "allowlist" in msg.lower() or "blocked" in msg.lower():
            raise BrowseDisabledError(msg) from exc
        raise
    return base


def _registry_get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    base = assert_browse_enabled()
    url = urljoin(base + "/", path.lstrip("/"))
    if params:
        url = f"{url}?{urlencode({k: v for k, v in params.items() if v is not None and v != ''})}"
    allow = skill_registry_allowlist()
    assert_safe_http_url(
        url,
        allow,
        empty_message=(
            "skill browser disabled: set CORVUS_SKILL_REGISTRY_ALLOWLIST "
            "to comma-separated URL prefixes"
        ),
    )
    req = Request(url, headers={"Accept": "application/json", "User-Agent": _USER_AGENT})
    try:
        with urlopen(req, timeout=30) as resp:  # noqa: S310 — allowlist gated
            raw = resp.read()
    except HTTPError as exc:
        raise ValueError(f"registry HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise ValueError(f"registry request failed: {exc.reason}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("registry returned non-JSON body") from exc


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _normalize_skill(raw: dict[str, Any]) -> BrowseSkill | None:
    owner = str(raw.get("owner") or "").strip()
    repo = str(raw.get("repo") or "").strip()
    source = str(raw.get("source") or "").strip()
    if (not owner or not repo) and "/" in source:
        owner, _, repo = source.partition("/")
        owner, repo = owner.strip(), repo.strip()
    skill_id = str(
        raw.get("id") or raw.get("skillId") or raw.get("skill_id") or raw.get("name") or ""
    ).strip()
    if not skill_id or not owner or not repo:
        return None
    name = str(raw.get("name") or skill_id).strip()
    description = str(raw.get("description") or "").strip()
    installs = _as_int(raw.get("installs") or raw.get("installCount") or 0)
    source_url = str(
        raw.get("source_url")
        or raw.get("url")
        or f"https://github.com/{owner}/{repo}"
    ).strip()
    return BrowseSkill(
        id=skill_id,
        name=name,
        description=description,
        owner=owner,
        repo=repo,
        installs=installs,
        source_url=source_url,
    )


def _extract_skill_list(payload: Any) -> tuple[list[BrowseSkill], dict[str, Any]]:
    items_raw: list[Any]
    meta: dict[str, Any] = {}
    if isinstance(payload, list):
        items_raw = payload
    elif isinstance(payload, dict):
        for key in ("skills", "data", "items", "results"):
            if isinstance(payload.get(key), list):
                items_raw = payload[key]
                break
        else:
            items_raw = []
        meta = {
            "page": payload.get("page"),
            "page_size": payload.get("pageSize") or payload.get("page_size"),
            "total": payload.get("total") or payload.get("totalCount"),
            "total_pages": payload.get("totalPages") or payload.get("total_pages"),
        }
    else:
        items_raw = []
    skills: list[BrowseSkill] = []
    for item in items_raw:
        if isinstance(item, dict):
            normalized = _normalize_skill(item)
            if normalized:
                skills.append(normalized)
    return skills, meta


def list_skills(
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    payload = _registry_get(
        "/api/skills",
        params={
            "query": query.strip() or None,
            "page": page,
            "pageSize": page_size,
        },
    )
    skills, meta = _extract_skill_list(payload)
    return {
        "enabled": True,
        "query": query.strip(),
        "page": meta.get("page") or page,
        "page_size": meta.get("page_size") or page_size,
        "total": meta.get("total"),
        "total_pages": meta.get("total_pages"),
        "skills": [s.as_dict() for s in skills],
    }


def get_skill(owner: str, repo: str, skill_id: str) -> dict[str, Any]:
    owner = owner.strip()
    repo = repo.strip()
    skill_id = skill_id.strip()
    if not owner or not repo or not skill_id:
        raise ValueError("owner, repo, and skill_id are required")
    path = (
        f"/api/skills/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/{quote(skill_id, safe='')}"
    )
    payload = _registry_get(path)
    if not isinstance(payload, dict):
        raise ValueError("registry detail returned unexpected shape")
    # Some APIs nest under "skill"
    raw = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
    skill = _normalize_skill(raw) if isinstance(raw, dict) else None
    if skill is None:
        skill = BrowseSkill(
            id=skill_id,
            name=skill_id,
            description=str(payload.get("description") or ""),
            owner=owner,
            repo=repo,
            installs=_as_int(payload.get("installs")),
            source_url=f"https://github.com/{owner}/{repo}",
        )
    content: Any = None
    try:
        content = _registry_get(f"{path}/content")
    except ValueError:
        content = None
    return {
        "skill": skill.as_dict(),
        "content": content,
        "registry": payload,
    }


def _http_get_bytes(url: str, *, allowlist: list[str], empty_message: str) -> bytes:
    assert_safe_http_url(url, allowlist, empty_message=empty_message)
    req = Request(url, headers={"User-Agent": _USER_AGENT, "Accept": "*/*"})
    try:
        with urlopen(req, timeout=60) as resp:  # noqa: S310 — allowlist gated
            return resp.read()
    except HTTPError as exc:
        raise ValueError(f"download HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise ValueError(f"download failed: {exc.reason}") from exc


def resolve_github_commit(owner: str, repo: str, ref: str) -> str:
    """Resolve ref to a full commit SHA via GitHub API (source allowlist gated)."""
    ref = ref.strip()
    if not ref or ref.lower() == "latest":
        raise ValueError("floating pin 'latest' is not allowed")
    if _SHA_RE.match(ref):
        return ref.lower()
    allow = parse_allowlist(os.environ.get("CORVUS_SKILL_SOURCE_ALLOWLIST", ""))
    api_url = (
        f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/commits/"
        f"{quote(ref, safe='')}"
    )
    raw = _http_get_bytes(
        api_url,
        allowlist=allow,
        empty_message=(
            "remote skill install denied: set CORVUS_SKILL_SOURCE_ALLOWLIST "
            "to include https://api.github.com/ and https://codeload.github.com/"
        ),
    )
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("GitHub commit resolve returned non-JSON") from exc
    sha = str(data.get("sha") or "").strip()
    if not _SHA_RE.match(sha):
        raise ValueError(f"could not resolve ref {ref!r} to a commit SHA")
    return sha.lower()


def github_archive_url(owner: str, repo: str, sha: str) -> str:
    return f"https://codeload.github.com/{owner}/{repo}/tar.gz/{sha}"


def prepare_install(
    *,
    owner: str,
    repo: str,
    skill_id: str,
    ref: str = "HEAD",
    allow_scripts: bool = False,
    dry_run: bool = True,
    store: SkillStore | None = None,
) -> dict[str, Any]:
    """Download GitHub archive, hash bytes, dry-run or commit via install_skill."""
    owner = owner.strip()
    repo = repo.strip()
    skill_id = skill_id.strip()
    if not owner or not repo or not skill_id:
        raise ValueError("owner, repo, and skill_id are required")
    sha = resolve_github_commit(owner, repo, ref)
    source = github_archive_url(owner, repo, sha)
    allow = parse_allowlist(os.environ.get("CORVUS_SKILL_SOURCE_ALLOWLIST", ""))
    blob = _http_get_bytes(
        source,
        allowlist=allow,
        empty_message=(
            "remote skill install denied: set CORVUS_SKILL_SOURCE_ALLOWLIST "
            "to include https://codeload.github.com/"
        ),
    )
    digest = hashlib.sha256(blob).hexdigest()
    result: InstallResult = install_skill(
        InstallRequest(
            source=source,
            pin=sha,
            sha256=digest,
            allow_scripts=allow_scripts,
            dry_run=dry_run,
            skill_id=skill_id,
        ),
        store=store,
    )
    return {
        "source": source,
        "pin": sha,
        "sha256": digest,
        "skill_id": skill_id,
        "owner": owner,
        "repo": repo,
        "dry_run": result.dry_run,
        "name": result.name,
        "version": result.version,
        "description": result.description,
        "content_hash": result.content_hash,
        "files": result.files,
        "allow_scripts": result.allow_scripts,
        "source_uri": result.source_uri,
        "source_pin": result.source_pin,
        "store_path": result.store_path,
        "entry": result.entry or None,
        "name_hint": skill_id,
        "files_preview": result.files,
    }
