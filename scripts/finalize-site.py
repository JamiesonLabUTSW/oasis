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


def fingerprint_project_assets() -> None:
    stylesheet = OUTPUT / "styles.css"
    if not stylesheet.is_file():
        raise SystemExit(f"rendered stylesheet is missing: {stylesheet}")
    version = digest(stylesheet)[:12]
    tour_runtime = OUTPUT / "product-tour.js"
    if not tour_runtime.is_file():
        raise SystemExit(f"rendered product-tour runtime is missing: {tour_runtime}")
    runtime_version = digest(tour_runtime)[:12]
    project_pages = sorted(OUTPUT.glob("*.html"))
    if not project_pages:
        raise SystemExit("no rendered project pages found for stylesheet fingerprinting")
    for page in project_pages:
        content = page.read_text(encoding="utf-8")
        original = 'href="styles.css"'
        if content.count(original) != 1:
            raise SystemExit(f"expected one project stylesheet link in {page}")
        content = content.replace(original, f'href="styles.css?v={version}"')
        runtime_original = 'src="product-tour.js"'
        runtime_count = content.count(runtime_original)
        if runtime_count > 1:
            raise SystemExit(f"expected at most one product-tour runtime link in {page}")
        if runtime_count == 1:
            content = content.replace(
                runtime_original,
                f'src="product-tour.js?v={runtime_version}"',
            )
        page.write_text(content, encoding="utf-8")


def main() -> None:
    if not OUTPUT.is_dir() or not PUBLICATION.is_file():
        raise SystemExit(f"rendered site is incomplete: {OUTPUT}")

    fingerprint_project_assets()

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

    demo_roots = {
        "cli-tui": OUTPUT / "assets" / "tui",
        "maples": OUTPUT / "assets" / "maples",
    }
    tours = {
        tour.get("id"): tour
        for tour in metadata.get("tours", [])
        if isinstance(tour, dict)
    }
    demo_media = []
    capture_manifests = []
    for tour_id, media_root in demo_roots.items():
        if not media_root.is_dir():
            raise SystemExit(f"recorded tour media is missing: {media_root}")
        media_assets = [
            artifact(path)
            for path in sorted(media_root.glob("*"))
            if path.is_file() and path.name not in {"manifest.json", "README.md"}
        ]
        demo_media.extend(media_assets)
        if tour_id not in tours:
            raise SystemExit(f"recorded tour metadata is missing: {tour_id}")
        tours[tour_id]["media_assets"] = media_assets

        manifest = media_root / "manifest.json"
        if not manifest.is_file():
            raise SystemExit(f"recorded tour manifest is missing: {manifest}")
        manifest_artifact = artifact(manifest)
        tours[tour_id]["capture_manifest"] = manifest_artifact
        capture_manifests.append({"tour_id": tour_id, **manifest_artifact})
        if tour_id == "cli-tui":
            metadata["software_demonstrations"]["capture_manifest"] = manifest_artifact

    metadata["demo_media"] = demo_media
    metadata["capture_manifests"] = capture_manifests
    PUBLICATION.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    rows = []
    for path in sorted(OUTPUT.rglob("*")):
        if not path.is_file() or path == CHECKSUMS:
            continue
        rows.append(f"{digest(path)}  ./{path.relative_to(OUTPUT).as_posix()}")
    CHECKSUMS.write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
