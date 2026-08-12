#!/usr/bin/env python3
"""Finalize deterministic OASIS project-site metadata and checksums."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "site" / "_site"
PUBLICATION = OUTPUT / "publication.json"
CHECKSUMS = OUTPUT / "SHA256SUMS"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def artifact(path: Path) -> dict[str, object]:
    relative = path.relative_to(OUTPUT).as_posix()
    return {
        "path": relative,
        "bytes": path.stat().st_size,
        "sha256": digest(path),
        "media_type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
    }


def fingerprint_site_styles() -> None:
    stylesheet = OUTPUT / "styles.css"
    if not stylesheet.is_file():
        raise SystemExit(f"rendered stylesheet is missing: {stylesheet}")
    version = digest(stylesheet)[:12]
    for page_name in ("index.html", "tui.html"):
        page = OUTPUT / page_name
        content = page.read_text(encoding="utf-8")
        original = 'href="styles.css"'
        if content.count(original) != 1:
            raise SystemExit(f"expected one project stylesheet link in {page}")
        page.write_text(
            content.replace(original, f'href="styles.css?v={version}"'),
            encoding="utf-8",
        )


def main() -> None:
    if not OUTPUT.is_dir() or not PUBLICATION.is_file():
        raise SystemExit(f"rendered site is incomplete: {OUTPUT}")

    fingerprint_site_styles()

    paper_site_libs = ROOT / "vendor" / "paper-site-libs"
    if not paper_site_libs.is_dir():
        raise SystemExit(f"prebuilt report support assets are missing: {paper_site_libs}")
    shutil.copytree(paper_site_libs, OUTPUT / "site_libs", dirs_exist_ok=True)

    metadata = json.loads(PUBLICATION.read_text(encoding="utf-8"))
    metadata["report_html"] = artifact(OUTPUT / "paper" / "paper.html")
    metadata["report_pdf"] = artifact(
        OUTPUT / "paper" / "OASIS_technical_report.pdf"
    )

    brand_names = (
        "oasis-logo-master.png",
        "oasis-logo.webp",
        "oasis-logo-nav.webp",
        "oasis-favicon.png",
        "oasis-tui-tour-master.png",
        "oasis-tui-tour-social.jpg",
    )
    metadata["brand_assets"] = [
        artifact(OUTPUT / "images" / name) for name in brand_names
    ]

    media_root = OUTPUT / "assets" / "tui"
    metadata["demo_media"] = [
        artifact(path)
        for path in sorted(media_root.glob("*"))
        if path.is_file() and path.name not in {"manifest.json", "README.md"}
    ]
    manifest = media_root / "manifest.json"
    if manifest.is_file():
        metadata["software_demonstrations"]["capture_manifest"] = artifact(manifest)
    PUBLICATION.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    rows = []
    for path in sorted(OUTPUT.rglob("*")):
        if not path.is_file() or path == CHECKSUMS:
            continue
        rows.append(f"{digest(path)}  ./{path.relative_to(OUTPUT).as_posix()}")
    CHECKSUMS.write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
