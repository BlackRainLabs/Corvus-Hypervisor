"""Browse allowlisted public Agent Skills registries (large open catalogs).

Supported adapters (auto-detected from ``CORVUS_SKILL_REGISTRY_URL``, or set
``CORVUS_SKILL_REGISTRY_ADAPTER``):

* ``skillsmp`` — SkillsMP marketplace (``/api/skills``, ``/api/v1/skills/search``)
* ``mastra`` — skills.sh-compatible servers (``/api/skills?query=&page=&pageSize=``)
* ``skills_sh`` — Vercel skills.sh v1 (``/api/v1/skills``; needs
  ``CORVUS_SKILL_REGISTRY_TOKEN``)

Install never trusts registry metadata alone — prepare-install still downloads
GitHub archives and verifies sha256 under ``CORVUS_SKILL_SOURCE_ALLOWLIST``.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from corvus.skills.install import InstallRequest, InstallResult, install_skill
from corvus.skills.netguard import assert_safe_http_url, parse_allowlist
from corvus.skills.store import SkillStore

_SHA_RE = re.compile(r"^[0-9a-f]{40}$", re.IGNORECASE)
_GITHUB_TREE_RE = re.compile(
    r"^https?://github\.com/(?P<owner>[^/]+)/(?P<repo>[^/]+)(?:/tree/(?P<ref>[^/]+)/(?P<path>.+))?/?$",
    re.IGNORECASE,
)
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
    stars: int = 0
    skill_path: str = ""
    ref_hint: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "owner": self.owner,
            "repo": self.repo,
            "installs": self.installs,
            "stars": self.stars,
            "source_url": self.source_url,
            "skill_path": self.skill_path,
            "ref_hint": self.ref_hint,
        }


def skill_registry_url() -> str:
    return (os.environ.get("CORVUS_SKILL_REGISTRY_URL") or "").strip().rstrip("/")


def skill_registry_allowlist() -> list[str]:
    return parse_allowlist(os.environ.get("CORVUS_SKILL_REGISTRY_ALLOWLIST", ""))


def skill_registry_token() -> str:
    return (os.environ.get("CORVUS_SKILL_REGISTRY_TOKEN") or "").strip()


def detect_adapter(base_url: str | None = None) -> str:
    forced = (os.environ.get("CORVUS_SKILL_REGISTRY_ADAPTER") or "").strip().lower()
    if forced in {"skillsmp", "mastra", "skills_sh"}:
        return forced
    host = (urlparse(base_url or skill_registry_url()).hostname or "").lower()
    if "skillsmp.com" in host:
        return "skillsmp"
    if host in {"skills.sh", "www.skills.sh"}:
        return "skills_sh"
    return "mastra"


def assert_browse_enabled() -> str:
    base = skill_registry_url()
    if not base:
        raise BrowseDisabledError(
            "skill browser disabled: set CORVUS_SKILL_REGISTRY_URL "
            "(recommended: https://skillsmp.com) and matching "
            "CORVUS_SKILL_REGISTRY_ALLOWLIST"
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
        msg = str(exc)
        if "allowlist" in msg.lower() or "blocked" in msg.lower():
            raise BrowseDisabledError(msg) from exc
        raise
    return base


def _registry_headers() -> dict[str, str]:
    headers = {"Accept": "application/json", "User-Agent": _USER_AGENT}
    token = skill_registry_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _registry_get(path: str, *, params: dict[str, Any] | None = None) -> Any:
    base = assert_browse_enabled()
    url = urljoin(base + "/", path.lstrip("/"))
    if params:
        clean = {k: v for k, v in params.items() if v is not None and v != ""}
        if clean:
            url = f"{url}?{urlencode(clean)}"
    allow = skill_registry_allowlist()
    assert_safe_http_url(
        url,
        allow,
        empty_message=(
            "skill browser disabled: set CORVUS_SKILL_REGISTRY_ALLOWLIST "
            "to comma-separated URL prefixes"
        ),
    )
    req = Request(url, headers=_registry_headers())
    try:
        with urlopen(req, timeout=45) as resp:  # noqa: S310 — allowlist gated
            raw = resp.read()
    except HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")[:200]
        except Exception:  # noqa: BLE001 — best-effort error body
            body = ""
        hint = f" ({body})" if body else ""
        raise ValueError(f"registry HTTP {exc.code} for {url}{hint}") from exc
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


def _parse_github_url(url: str) -> tuple[str, str, str, str]:
    """Return (owner, repo, ref_hint, skill_dir_or_path)."""
    m = _GITHUB_TREE_RE.match((url or "").strip())
    if not m:
        return "", "", "", ""
    owner = m.group("owner") or ""
    repo = m.group("repo") or ""
    ref = m.group("ref") or ""
    path = (m.group("path") or "").strip("/")
    skill_dir = path.rsplit("/", 1)[-1] if path else ""
    return owner, repo, ref, skill_dir or path


def _normalize_skill(raw: dict[str, Any]) -> BrowseSkill | None:
    owner = str(raw.get("owner") or "").strip()
    repo = str(raw.get("repo") or "").strip()
    source = str(raw.get("source") or "").strip()
    github_url = str(
        raw.get("githubUrl") or raw.get("github_url") or raw.get("installUrl") or ""
    ).strip()
    route = raw.get("route") if isinstance(raw.get("route"), dict) else {}
    if not owner:
        owner = str(route.get("ownerSlug") or raw.get("author") or "").strip()
    if not repo:
        repo = str(route.get("repoSlug") or "").strip()
    if (not owner or not repo) and "/" in source:
        owner, _, repo = source.partition("/")
        owner, repo = owner.strip(), repo.strip()
    ref_hint = str(raw.get("branch") or "").strip()
    skill_path = str(
        route.get("sourceSkillPath") or raw.get("path") or raw.get("skill_path") or ""
    ).strip()
    if github_url:
        g_owner, g_repo, g_ref, g_dir = _parse_github_url(github_url)
        owner = owner or g_owner
        repo = repo or g_repo
        if g_ref and not ref_hint:
            ref_hint = g_ref
        if not skill_path and g_dir:
            skill_path = g_dir

    # Prefer short package/folder name for install skill_id lookup.
    name = str(raw.get("name") or "").strip()
    skill_id = name or str(
        raw.get("slug") or raw.get("skillId") or raw.get("skill_id") or ""
    ).strip()
    if not skill_id and skill_path:
        skill_id = skill_path.rstrip("/").rsplit("/", 1)[-1]
        if skill_id.lower() == "skill.md":
            skill_id = skill_path.rstrip("/").rsplit("/", 2)[-2] if "/" in skill_path else ""
    catalog_id = str(raw.get("id") or skill_id).strip()
    if not skill_id:
        skill_id = catalog_id
    if not skill_id or not owner or not repo:
        return None

    description = str(raw.get("description") or "").strip()
    installs = _as_int(
        raw.get("installs") or raw.get("installCount") or raw.get("install_count") or 0
    )
    stars = _as_int(raw.get("stars") or raw.get("stargazers_count") or 0)
    source_url = str(
        raw.get("source_url")
        or raw.get("skillUrl")
        or github_url
        or raw.get("url")
        or f"https://github.com/{owner}/{repo}"
    ).strip()
    return BrowseSkill(
        id=skill_id,
        name=name or skill_id,
        description=description,
        owner=owner,
        repo=repo,
        installs=installs or stars,
        stars=stars,
        source_url=source_url,
        skill_path=skill_path,
        ref_hint=ref_hint,
    )


def _unwrap_list_payload(payload: Any) -> tuple[list[Any], dict[str, Any]]:
    """Normalize diverse registry list envelopes into (items, pagination meta)."""
    meta: dict[str, Any] = {}
    if isinstance(payload, list):
        return payload, meta
    if not isinstance(payload, dict):
        return [], meta

    # SkillsMP v1 search: { success, data: { skills, pagination } }
    data = payload.get("data")
    if isinstance(data, dict) and isinstance(data.get("skills"), list):
        pag = data.get("pagination") if isinstance(data.get("pagination"), dict) else {}
        meta = {
            "page": pag.get("page"),
            "page_size": pag.get("limit") or pag.get("pageSize") or pag.get("page_size"),
            "total": pag.get("total") or pag.get("totalCount"),
            "total_pages": pag.get("totalPages") or pag.get("total_pages"),
            "has_next": pag.get("hasNext") or pag.get("hasMore") or pag.get("has_next"),
            "has_prev": pag.get("hasPrev") or pag.get("has_prev"),
        }
        return data["skills"], meta

    if isinstance(payload.get("skills"), list):
        pag = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        meta = {
            "page": pag.get("page") or payload.get("page"),
            "page_size": (
                pag.get("limit")
                or pag.get("pageSize")
                or payload.get("pageSize")
                or payload.get("page_size")
            ),
            "total": pag.get("total") or payload.get("total") or payload.get("totalCount"),
            "total_pages": pag.get("totalPages") or payload.get("totalPages"),
            "has_next": pag.get("hasNext") or pag.get("hasMore"),
            "has_prev": pag.get("hasPrev"),
        }
        return payload["skills"], meta

    if isinstance(data, list):
        pag = payload.get("pagination") if isinstance(payload.get("pagination"), dict) else {}
        meta = {
            "page": pag.get("page") or payload.get("page"),
            "page_size": pag.get("per_page") or pag.get("limit") or payload.get("pageSize"),
            "total": pag.get("totalCount") or pag.get("total") or payload.get("total"),
            "total_pages": pag.get("totalPages"),
            "has_next": pag.get("hasMore") or pag.get("hasNextPage"),
            "has_prev": pag.get("hasPrevPage"),
        }
        return data, meta

    for key in ("items", "results"):
        if isinstance(payload.get(key), list):
            return payload[key], {
                "page": payload.get("page"),
                "page_size": payload.get("pageSize") or payload.get("page_size"),
                "total": payload.get("total") or payload.get("totalCount"),
                "total_pages": payload.get("totalPages") or payload.get("total_pages"),
            }
    return [], meta


def _extract_skill_list(payload: Any) -> tuple[list[BrowseSkill], dict[str, Any]]:
    items_raw, meta = _unwrap_list_payload(payload)
    skills: list[BrowseSkill] = []
    for item in items_raw:
        if isinstance(item, dict):
            normalized = _normalize_skill(item)
            if normalized:
                skills.append(normalized)
    return skills, meta


def _list_skillsmp(*, query: str, page: int, page_size: int) -> Any:
    q = query.strip()
    if q:
        return _registry_get(
            "/api/v1/skills/search",
            params={"q": q, "page": page, "limit": page_size},
        )
    return _registry_get(
        "/api/skills",
        params={"page": page, "limit": page_size, "sortBy": "stars"},
    )


def _list_mastra(*, query: str, page: int, page_size: int) -> Any:
    return _registry_get(
        "/api/skills",
        params={
            "query": query.strip() or None,
            "page": page,
            "pageSize": page_size,
        },
    )


def _list_skills_sh(*, query: str, page: int, page_size: int) -> Any:
    # skills.sh pages are 0-indexed; Corvus UI uses 1-indexed pages.
    if not skill_registry_token():
        raise ValueError(
            "skills.sh adapter requires CORVUS_SKILL_REGISTRY_TOKEN "
            "(Bearer token — see https://skills.sh/docs/api)"
        )
    q = query.strip()
    if q:
        return _registry_get(
            "/api/v1/skills/search",
            params={"q": q, "limit": page_size},
        )
    return _registry_get(
        "/api/v1/skills",
        params={
            "view": "all-time",
            "page": max(0, page - 1),
            "per_page": page_size,
        },
    )


def list_skills(
    *,
    query: str = "",
    page: int = 1,
    page_size: int = 20,
) -> dict[str, Any]:
    page = max(1, int(page))
    page_size = min(100, max(1, int(page_size)))
    base = assert_browse_enabled()
    adapter = detect_adapter(base)
    if adapter == "skillsmp":
        payload = _list_skillsmp(query=query, page=page, page_size=page_size)
    elif adapter == "skills_sh":
        payload = _list_skills_sh(query=query, page=page, page_size=page_size)
    else:
        payload = _list_mastra(query=query, page=page, page_size=page_size)

    skills, meta = _extract_skill_list(payload)
    total = meta.get("total")
    total_pages = meta.get("total_pages")
    if total_pages is None and isinstance(total, int) and page_size:
        total_pages = max(1, (int(total) + page_size - 1) // page_size)
    has_next = meta.get("has_next")
    if has_next is None and total_pages is not None:
        has_next = page < int(total_pages)
    has_prev = meta.get("has_prev")
    if has_prev is None:
        has_prev = page > 1

    return {
        "enabled": True,
        "adapter": adapter,
        "registry_url": base,
        "query": query.strip(),
        "page": int(meta.get("page") or page),
        "page_size": int(meta.get("page_size") or page_size),
        "total": total,
        "total_pages": total_pages,
        "has_next": bool(has_next),
        "has_prev": bool(has_prev),
        "skills": [s.as_dict() for s in skills],
    }


def get_skill(owner: str, repo: str, skill_id: str) -> dict[str, Any]:
    owner = owner.strip()
    repo = repo.strip()
    skill_id = skill_id.strip()
    if not owner or not repo or not skill_id:
        raise ValueError("owner, repo, and skill_id are required")
    base = assert_browse_enabled()
    adapter = detect_adapter(base)
    if adapter == "skillsmp":
        # No stable detail path — search by skill name and filter.
        payload = _list_skillsmp(query=skill_id, page=1, page_size=20)
        skills, _ = _extract_skill_list(payload)
        for skill in skills:
            if (
                skill.owner == owner
                and skill.repo == repo
                and skill.id == skill_id
            ):
                return {"skill": skill.as_dict(), "content": None, "registry": None}
        raise ValueError(f"skill not found in registry: {owner}/{repo}/{skill_id}")

    path = (
        f"/api/skills/{quote(owner, safe='')}/"
        f"{quote(repo, safe='')}/{quote(skill_id, safe='')}"
    )
    payload = _registry_get(path)
    if not isinstance(payload, dict):
        raise ValueError("registry detail returned unexpected shape")
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
