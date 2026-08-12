#!/usr/bin/env python3
"""Validate the rendered OASIS project site with standard-library checks."""

from __future__ import annotations

import hashlib
import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = (ROOT / "site" / "_site").resolve()
CHECKSUMS = OUTPUT / "SHA256SUMS"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


class ReferenceParser(HTMLParser):
    def __init__(self, page: Path) -> None:
        super().__init__()
        self.page = page
        self.references: list[str] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        for key in ("href", "src", "srcset"):
            raw = (values.get(key) or "").strip()
            if raw:
                self.references.append(raw.split()[0])


def check_references() -> None:
    problems = []
    for page in OUTPUT.rglob("*.html"):
        parser = ReferenceParser(page)
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        for reference in parser.references:
            if reference.startswith(("#", "http:", "https:", "mailto:", "data:", "javascript:")):
                continue
            path = urlsplit(reference).path
            target = OUTPUT / path.lstrip("/") if path.startswith("/") else page.parent / path
            target = target.resolve()
            try:
                target.relative_to(OUTPUT)
            except ValueError:
                problems.append(f"{page.relative_to(OUTPUT)}: reference escapes site: {reference}")
                continue
            if target.is_dir():
                target /= "index.html"
            if not target.exists():
                problems.append(f"{page.relative_to(OUTPUT)}: missing target: {reference}")
    if problems:
        raise SystemExit("\n".join(problems))


def check_media_manifest() -> None:
    manifest_path = OUTPUT / "assets" / "tui" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assets = manifest.get("assets", [])
    if len(assets) != 20:
        raise SystemExit(f"expected 20 recorded media assets, found {len(assets)}")
    for item in assets:
        path = OUTPUT / item["path"]
        if not path.is_file():
            raise SystemExit(f"manifest asset missing: {item['path']}")
        if path.stat().st_size != item["bytes"]:
            raise SystemExit(f"manifest size mismatch: {item['path']}")
        if digest(path) != item["sha256"]:
            raise SystemExit(f"manifest hash mismatch: {item['path']}")


def check_checksums() -> None:
    expected = {
        path.relative_to(OUTPUT).as_posix()
        for path in OUTPUT.rglob("*")
        if path.is_file() and path != CHECKSUMS
    }
    observed: dict[str, str] = {}
    for line in CHECKSUMS.read_text(encoding="utf-8").splitlines():
        hash_value, marker, name = line.partition("  ./")
        if not marker or len(hash_value) != 64:
            raise SystemExit(f"malformed checksum row: {line}")
        if name in observed:
            raise SystemExit(f"duplicate checksum row: {name}")
        observed[name] = hash_value
    if set(observed) != expected:
        missing = sorted(expected - set(observed))
        extra = sorted(set(observed) - expected)
        raise SystemExit(f"checksum coverage mismatch; missing={missing}, extra={extra}")
    for name, hash_value in observed.items():
        if digest(OUTPUT / name) != hash_value:
            raise SystemExit(f"checksum mismatch: {name}")


def check_contract() -> None:
    tui = (OUTPUT / "tui.html").read_text(encoding="utf-8")
    for marker in (
        'role="tablist"',
        '<h2 id="tour-view-title">',
        'id="tour-view-summary"',
        'id="tour-tab-dashboard"',
        'id="tour-tab-results"',
        'id="tour-video-dialog"',
        'src="tour.js"',
        "Recorded · sanitized · offline",
    ):
        if marker not in tui:
            raise SystemExit(f"interactive tour marker missing: {marker}")

    publication = json.loads((OUTPUT / "publication.json").read_text(encoding="utf-8"))
    demo = publication.get("software_demonstrations", {})
    if not (demo.get("recorded") and demo.get("sanitized") and demo.get("live_service") is False):
        raise SystemExit("publication demonstration scope is not explicit")
    if len(publication.get("demo_media", [])) != 20:
        raise SystemExit("publication media inventory is incomplete")
    brand_assets = publication.get("brand_assets", [])
    if len(brand_assets) != 6:
        raise SystemExit("publication brand-asset inventory is incomplete")
    brand_paths = {item.get("path") for item in brand_assets}
    required_brand_paths = {
        "images/oasis-logo-master.png",
        "images/oasis-logo.webp",
        "images/oasis-logo-nav.webp",
        "images/oasis-favicon.png",
        "images/oasis-tui-tour-master.png",
        "images/oasis-tui-tour-social.jpg",
    }
    if brand_paths != required_brand_paths:
        raise SystemExit("publication brand-asset inventory has unexpected paths")
    for item in brand_assets:
        path = OUTPUT / item["path"]
        if path.stat().st_size != item["bytes"] or digest(path) != item["sha256"]:
            raise SystemExit(f"publication brand-asset mismatch: {item['path']}")

    forbidden = ("/Users/", "/home2/", "/endosome/", "BEGIN PRIVATE KEY")
    text_suffixes = {".css", ".html", ".js", ".json", ".md", ".txt", ".yml", ".yaml"}
    for path in OUTPUT.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in text_suffixes:
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for value in forbidden:
            if value in content:
                raise SystemExit(f"private path or secret marker in {path.relative_to(OUTPUT)}: {value}")


def main() -> None:
    if not (OUTPUT / "index.html").is_file() or not (OUTPUT / "tui.html").is_file():
        raise SystemExit(f"rendered site is incomplete: {OUTPUT}")
    check_references()
    check_media_manifest()
    check_checksums()
    check_contract()
    print("OASIS project site checks: PASS")


if __name__ == "__main__":
    main()
