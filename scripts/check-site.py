#!/usr/bin/env python3
"""Validate the rendered OASIS project site with standard-library checks."""

from __future__ import annotations

import hashlib
import json
import re
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


def relative_luminance(hex_color: str) -> float:
    channels = [
        int(hex_color[index : index + 2], 16) / 255
        for index in (1, 3, 5)
    ]
    linear = [
        channel / 12.92
        if channel <= 0.04045
        else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def contrast_ratio(first: str, second: str) -> float:
    brighter, darker = sorted(
        (relative_luminance(first), relative_luminance(second)),
        reverse=True,
    )
    return (brighter + 0.05) / (darker + 0.05)


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
    if manifest.get("schema_version") != "oasis.tui-site-media.v2":
        raise SystemExit("recorded media manifest is not the truecolor v2 contract")

    capture = manifest.get("capture", {})
    environment = capture.get("environment", {})
    if environment.get("TERM") != "xterm-256color" or environment.get("COLORTERM") != "truecolor":
        raise SystemExit("recorded media was not captured in a truecolor terminal")
    forbidden_color_controls = {"NO_COLOR", "CLICOLOR_FORCE", "FORCE_COLOR"}
    if not forbidden_color_controls.issubset(set(environment.get("unset", []))):
        raise SystemExit("recorded media does not prove color-suppression controls were unset")

    proof = manifest.get("truecolor_proof", {})
    if not proof.get("gate") or proof.get("truecolor_foreground_count", 0) <= 0 or proof.get("truecolor_background_count", 0) <= 0:
        raise SystemExit("recorded media is missing its truecolor ANSI proof")
    metrics = proof.get("color_metrics", {})
    expected_scenes = {"splash", "dashboard", "workflow", "results", "elephant"}
    if set(metrics) != expected_scenes or not all(item.get("materially_greater") for item in metrics.values()):
        raise SystemExit("recorded media is missing corrected color evidence for every scene")

    content_review = manifest.get("content_review", {})
    if not content_review.get("all_frames_passed") or content_review.get("sensitive_or_unexpected_error_hit_lines") != 0:
        raise SystemExit("recorded media did not pass its all-frame safety review")

    assets = manifest.get("assets", [])
    if len(assets) != 20:
        raise SystemExit(f"expected 20 recorded media assets, found {len(assets)}")
    if {item.get("scene") for item in assets} != expected_scenes:
        raise SystemExit("recorded media scene inventory is incomplete")
    for item in assets:
        path = OUTPUT / item["path"]
        if not path.is_file():
            raise SystemExit(f"manifest asset missing: {item['path']}")
        if path.stat().st_size != item["bytes"]:
            raise SystemExit(f"manifest size mismatch: {item['path']}")
        if digest(path) != item["sha256"]:
            raise SystemExit(f"manifest hash mismatch: {item['path']}")
        if item.get("format") in {"webm", "mp4", "gif"} and item.get("audio_streams") != 0:
            raise SystemExit(f"recorded media unexpectedly contains audio: {item['path']}")


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
    for page_name in ("index.html", "tui.html"):
        page = (OUTPUT / page_name).read_text(encoding="utf-8")
        stylesheet_links = re.findall(
            r'href="styles\.css\?v=([0-9a-f]{12})"',
            page,
        )
        if len(stylesheet_links) != 1:
            raise SystemExit(f"project stylesheet is not fingerprinted in {page_name}")
        if stylesheet_links[0] != digest(OUTPUT / "styles.css")[:12]:
            raise SystemExit(f"project stylesheet fingerprint is stale in {page_name}")

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

    styles = (OUTPUT / "styles.css").read_text(encoding="utf-8")
    nav_palette = {}
    for name in ("bg", "text", "active", "brand", "hover"):
        match = re.search(
            rf"--oasis-nav-{name}\s*:\s*(#[0-9a-fA-F]{{6}})\s*;",
            styles,
        )
        if not match:
            raise SystemExit(f"navbar palette color is missing: {name}")
        nav_palette[name] = match.group(1)
    for name in ("text", "active", "brand", "hover"):
        ratio = contrast_ratio(nav_palette[name], nav_palette["bg"])
        if ratio < 4.5:
            raise SystemExit(f"navbar {name} contrast is below WCAG AA: {ratio:.2f}:1")

    teaser_rules = re.findall(r"\.tour-teaser-media img\s*\{([^}]*)\}", styles)
    ratio_rule = next(
        (rule for rule in teaser_rules if "aspect-ratio" in rule),
        None,
    )
    if not ratio_rule or not re.search(r"\bheight\s*:\s*auto\s*;", ratio_rule):
        raise SystemExit("homepage TUI teaser does not preserve its intrinsic aspect ratio")
    if not re.search(r"\baspect-ratio\s*:\s*5\s*/\s*3\s*;", ratio_rule):
        raise SystemExit("homepage TUI teaser is missing its 5:3 media contract")

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
