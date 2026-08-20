#!/usr/bin/env python3
"""Validate the rendered OASIS project site with standard-library checks."""

from __future__ import annotations

import hashlib
import json
import re
import struct
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


class TourStructureParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []
        self.tabs: list[dict[str, str]] = []
        self.stages: list[dict[str, str]] = []

    def handle_starttag(self, _tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        if values.get("id"):
            self.ids.append(values["id"])
        if values.get("data-role") == "tab":
            self.tabs.append(values)
        if values.get("data-role") == "stage":
            self.stages.append(values)


def extract_tour_payload(page_name: str, content: str) -> dict[str, object]:
    matches = re.findall(
        r'<script type="application/json" data-product-tour-data(?:="")?>\s*(.*?)\s*</script>',
        content,
        flags=re.DOTALL,
    )
    if len(matches) != 1:
        raise SystemExit(f"expected one product-tour data block in {page_name}")
    return json.loads(matches[0])


def check_tour_structure(page_name: str, expected_steps: list[str]) -> dict[str, object]:
    page = OUTPUT / page_name
    content = page.read_text(encoding="utf-8")
    payload = extract_tour_payload(page_name, content)
    steps = payload.get("steps", [])
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        raise SystemExit(f"product-tour steps are invalid in {page_name}")
    step_ids = [step.get("id") for step in steps if isinstance(step, dict)]
    if step_ids != expected_steps:
        raise SystemExit(f"product-tour step order is invalid in {page_name}: {step_ids}")

    structure = TourStructureParser()
    structure.feed(content)
    duplicate_ids = sorted({value for value in structure.ids if structure.ids.count(value) > 1})
    if duplicate_ids:
        raise SystemExit(f"duplicate HTML ids in {page_name}: {duplicate_ids}")
    if [tab.get("data-step") for tab in structure.tabs] != expected_steps:
        raise SystemExit(f"tour tabs do not match step data in {page_name}")
    if len(structure.stages) != 1:
        raise SystemExit(f"expected one tour stage in {page_name}")
    known_ids = set(structure.ids)
    for index, tab in enumerate(structure.tabs):
        if not tab.get("id") or tab.get("aria-controls") not in known_ids:
            raise SystemExit(f"tour tab has a broken ARIA target in {page_name}")
        expected_selected = "true" if index == 0 else "false"
        if tab.get("aria-selected") != expected_selected:
            raise SystemExit(f"tour tab selection state is invalid in {page_name}")
    if structure.stages[0].get("aria-labelledby") != structure.tabs[0].get("id"):
        raise SystemExit(f"tour stage label is invalid in {page_name}")

    def require_local_asset(reference: str) -> None:
        if not isinstance(reference, str):
            raise SystemExit(f"tour JSON asset path is invalid in {page_name}")
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or not parsed.path:
            raise SystemExit(f"tour JSON asset must be local in {page_name}: {reference}")
        target = (page.parent / parsed.path).resolve()
        try:
            target.relative_to(OUTPUT)
        except ValueError as error:
            raise SystemExit(f"tour JSON asset escapes the site in {page_name}: {reference}") from error
        if not target.is_file():
            raise SystemExit(f"tour JSON asset is missing in {page_name}: {reference}")

    for step in steps:
        if not all(isinstance(step.get(key), str) and step[key].strip() for key in ("id", "label", "title", "summary")):
            raise SystemExit(f"tour step copy is incomplete in {page_name}")
        poster = step.get("poster")
        if poster is not None:
            if not isinstance(poster, dict) or not poster.get("alt"):
                raise SystemExit(f"tour poster metadata is incomplete in {page_name}")
            require_local_asset(poster.get("src", ""))
            for candidate in poster.get("srcset", "").split(","):
                candidate = candidate.strip()
                if candidate:
                    require_local_asset(candidate.split()[0])
        media = step.get("media")
        if media is not None:
            if not isinstance(media, dict):
                raise SystemExit(f"tour media metadata is invalid in {page_name}")
            for key in ("webm", "mp4", "gif"):
                if media.get(key):
                    require_local_asset(media[key])
    return payload


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


def parse_static_webp(path: Path) -> list[str]:
    data = path.read_bytes()
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise SystemExit(f"invalid WebP container: {path.relative_to(OUTPUT)}")
    declared_size = struct.unpack_from("<I", data, 4)[0] + 8
    if declared_size != len(data):
        raise SystemExit(f"WebP RIFF length mismatch: {path.relative_to(OUTPUT)}")
    chunks = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise SystemExit(f"truncated WebP chunk header: {path.relative_to(OUTPUT)}")
        name = data[offset : offset + 4].decode("ascii", errors="strict")
        size = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8
        if offset + size > len(data):
            raise SystemExit(f"truncated WebP chunk: {path.relative_to(OUTPUT)}")
        chunks.append(name)
        offset += size + (size % 2)
    if offset != len(data):
        raise SystemExit(f"trailing WebP data: {path.relative_to(OUTPUT)}")
    forbidden = {"EXIF", "XMP ", "ICCP", "ANIM", "ANMF"}
    if forbidden.intersection(chunks) or chunks != ["VP8 "]:
        raise SystemExit(
            f"MAPLES poster is not a metadata-free static WebP: "
            f"{path.relative_to(OUTPUT)} chunks={chunks}"
        )
    return chunks


def check_maples_media_manifest() -> dict[str, object]:
    manifest_path = OUTPUT / "assets" / "maples" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != "oasis.maples-site-media.v1":
        raise SystemExit("MAPLES media manifest schema is invalid")

    scenario = manifest.get("scenario", {})
    if (
        scenario.get("id") != "intern-perfume-to-candle-v1"
        or scenario.get("source_data_reused") is not False
        or scenario.get("source_media_reused") is not False
        or scenario.get("original_prompts_or_outputs_reused") is not False
        or scenario.get("student_or_patient_data") is not False
        or scenario.get("visible_record_ids") != ["DEMO-001", "DEMO-002", "DEMO-003"]
    ):
        raise SystemExit("MAPLES fixture provenance or privacy scope is invalid")

    application = manifest.get("application", {})
    if (
        application.get("source_sha")
        != "90031150529bbfa1a3de4f5769039fb91940ed08"
        or application.get("maples_tree_sha")
        != "f7577341a2e04f6e5efa32298904e55d5f2cc04e"
        or application.get("tracked_source_clean") is not True
        or application.get("live_maples_stack") is not False
    ):
        raise SystemExit("MAPLES capture source identity is invalid")

    execution = manifest.get("execution_boundary", {})
    if (
        execution.get("grading_pipeline_invoked") is not False
        or execution.get("provider_calls") != 0
        or execution.get("network_clients") != 0
        or execution.get("spend_usd") != 0
        or execution.get("displayed_scores_are_fixture_values") is not True
        or execution.get("visitor_network_calls") is not False
        or execution.get("unexpected_non_2xx") != 0
    ):
        raise SystemExit("MAPLES zero-provider execution boundary is invalid")

    privacy = manifest.get("privacy_review", {})
    if (
        privacy.get("dom_scenes_reviewed") != 7
        or privacy.get("ocr_scenes_reviewed") != 7
        or privacy.get("manual_scenes_reviewed") != 7
        or privacy.get("sensitive_hits") != 0
        or privacy.get("real_person_data_visible") is not False
        or privacy.get("all_passed") is not True
    ):
        raise SystemExit("MAPLES media privacy review is incomplete")

    delivery = manifest.get("delivery", {})
    assets = manifest.get("assets", [])
    expected_scenes = [
        "group",
        "rubric-path",
        "rubric",
        "mapping",
        "launch",
        "results",
        "review",
    ]
    expected_paths = [
        f"assets/maples/maples-{index:02d}-{scene}.webp"
        for index, scene in enumerate(expected_scenes, start=1)
    ]
    if (
        delivery.get("asset_count") != 7
        or delivery.get("motion_media_included") is not False
        or len(assets) != 7
        or [item.get("order") for item in assets] != list(range(1, 8))
        or [item.get("scene") for item in assets] != expected_scenes
        or [item.get("path") for item in assets] != expected_paths
    ):
        raise SystemExit("MAPLES poster inventory is incomplete or out of order")

    observed_total = 0
    for item in assets:
        path = OUTPUT / item["path"]
        if not path.is_file():
            raise SystemExit(f"MAPLES poster is missing: {item['path']}")
        if (
            item.get("format") != "webp"
            or item.get("width") != 1200
            or item.get("height") != 720
            or item.get("metadata_chunks") != ["VP8"]
            or not item.get("alt")
            or item.get("bytes") != path.stat().st_size
            or item.get("sha256") != digest(path)
            or path.stat().st_size > delivery.get("per_file_cap_bytes", 0)
        ):
            raise SystemExit(f"MAPLES poster metadata mismatch: {item['path']}")
        review = item.get("manual_review", {})
        if (
            review.get("passed") is not True
            or review.get("real_person_data_visible") is not False
            or review.get("browser_or_os_chrome_visible") is not False
            or review.get("redaction_or_blur_used") is not False
        ):
            raise SystemExit(f"MAPLES poster manual review is incomplete: {item['path']}")
        parse_static_webp(path)
        observed_total += path.stat().st_size
    if (
        observed_total != delivery.get("total_bytes")
        or observed_total > delivery.get("aggregate_cap_bytes", 0)
    ):
        raise SystemExit("MAPLES poster aggregate byte contract is invalid")
    return manifest


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
    for page_name in ("index.html", "explore.html", "tui.html", "maples.html"):
        page = (OUTPUT / page_name).read_text(encoding="utf-8")
        stylesheet_links = re.findall(
            r'href="styles\.css\?v=([0-9a-f]{12})"',
            page,
        )
        if len(stylesheet_links) != 1:
            raise SystemExit(f"project stylesheet is not fingerprinted in {page_name}")
        if stylesheet_links[0] != digest(OUTPUT / "styles.css")[:12]:
            raise SystemExit(f"project stylesheet fingerprint is stale in {page_name}")

    for page_name in ("tui.html", "maples.html"):
        page = (OUTPUT / page_name).read_text(encoding="utf-8")
        runtime_links = re.findall(
            r'src="product-tour\.js\?v=([0-9a-f]{12})"',
            page,
        )
        if len(runtime_links) != 1:
            raise SystemExit(f"product-tour runtime is not fingerprinted in {page_name}")
        if runtime_links[0] != digest(OUTPUT / "product-tour.js")[:12]:
            raise SystemExit(f"product-tour runtime fingerprint is stale in {page_name}")

    tui = (OUTPUT / "tui.html").read_text(encoding="utf-8")
    for marker in (
        'role="tablist"',
        '<h2 id="tour-view-title"',
        'id="tour-view-summary"',
        'id="tour-tab-dashboard"',
        'id="tour-tab-results"',
        'id="product-tour-dialog"',
        'src="product-tour.js?v=',
        'data-product-tour-data',
        "Recorded · sanitized · offline",
    ):
        if marker not in tui:
            raise SystemExit(f"interactive tour marker missing: {marker}")
    check_tour_structure(
        "tui.html",
        ["splash", "dashboard", "workflow", "results", "elephant"],
    )

    maples = (OUTPUT / "maples.html").read_text(encoding="utf-8")
    for marker in (
        'data-tour-id="maples"',
        'id="maples-tab-group"',
        'id="maples-tab-review"',
        'id="maples-tab-rubric-path"',
        'src="product-tour.js?v=',
        "Recorded deterministic fixture · coded synthetic data · zero provider calls",
        "Displayed scores, rationales, progress, and review states are authored fixture values",
        "No grading pipeline was launched for this capture",
        "Wayfinder Rubric Studio",
    ):
        if marker not in maples:
            raise SystemExit(f"MAPLES tour marker missing: {marker}")
    maples_og_images = re.findall(
        r'<meta property="og:image" content="([^"]+)">',
        maples,
    )
    expected_maples_og_image = (
        "https://jamiesonlabutsw.github.io/oasis/"
        "assets/maples/maples-01-group.webp"
    )
    if maples_og_images and maples_og_images != [expected_maples_og_image]:
        raise SystemExit(
            f"MAPLES tour has an unexpected social image: {maples_og_images}"
        )

    expected_steps = ["group", "rubric-path", "rubric", "mapping", "launch", "results", "review"]
    payload = check_tour_structure("maples.html", expected_steps)
    maples_manifest = json.loads(
        (OUTPUT / "assets" / "maples" / "manifest.json").read_text(encoding="utf-8")
    )
    manifest_assets = {
        item["scene"]: item
        for item in maples_manifest["assets"]
    }
    for step in payload["steps"]:
        poster = step.get("poster")
        asset = manifest_assets.get(step.get("id"))
        if (
            not isinstance(poster, dict)
            or asset is None
            or poster.get("src") != asset.get("path")
            or poster.get("srcset") != asset.get("path")
            or poster.get("type") != "image/webp"
            or poster.get("width") != 1200
            or poster.get("height") != 720
            or poster.get("alt") != asset.get("alt")
            or step.get("media") is not None
        ):
            raise SystemExit(f"MAPLES tour poster contract is invalid: {step.get('id')}")
    for forbidden_claim in (
        "capture pending",
        "Capture planned",
        "Start and monitor grading",
        "Inspect the AI score",
        "Accept the AI score",
    ):
        if forbidden_claim in maples:
            raise SystemExit(f"MAPLES recorded-fixture copy overclaims its capture: {forbidden_claim}")

    explore = (OUTPUT / "explore.html").read_text(encoding="utf-8")
    for marker in (
        "Choose a journey",
        "Open the CLI &amp; TUI tour",
        "Open the MAPLES tour",
        "Available now · recorded",
        "Available now · recorded fixture",
    ):
        if marker not in explore:
            raise SystemExit(f"Explore overview marker missing: {marker}")

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

    interaction_palette = {}
    for name in (
        "cream",
        "link",
        "link-hover",
        "dark-link",
        "night-soft",
        "teal",
        "on-teal",
        "focus",
    ):
        match = re.search(
            rf"--oasis-{name}\s*:\s*(#[0-9a-fA-F]{{6}})\s*;",
            styles,
        )
        if not match:
            raise SystemExit(f"interaction palette color is missing: {name}")
        interaction_palette[name] = match.group(1)
    interaction_contrast = {
        "body link": contrast_ratio(
            interaction_palette["link"], interaction_palette["cream"]
        ),
        "body link hover": contrast_ratio(
            interaction_palette["link-hover"], interaction_palette["cream"]
        ),
        "CTA text": contrast_ratio(
            interaction_palette["on-teal"], interaction_palette["teal"]
        ),
        "dark-surface link": contrast_ratio(
            interaction_palette["dark-link"], interaction_palette["night-soft"]
        ),
    }
    for name, ratio in interaction_contrast.items():
        if ratio < 4.5:
            raise SystemExit(f"{name} contrast is below WCAG AA: {ratio:.2f}:1")
    focus_ratio = contrast_ratio(
        interaction_palette["focus"], interaction_palette["cream"]
    )
    if focus_ratio < 3.0:
        raise SystemExit(
            f"light-surface focus contrast is below 3:1: {focus_ratio:.2f}:1"
        )
    for selector_contract in (
        r"body\s+a\s*\{[^}]*color:\s*var\(--oasis-link\)",
        r"body\s+a:hover,\s*body\s+a:focus\s*\{[^}]*color:\s*var\(--oasis-link-hover\)",
        r"\.tour-cta:hover,\s*\.tour-cta:focus\s*\{[^}]*color:\s*var\(--oasis-on-teal\)",
        r"\.tour-deep-link:hover,\s*\.tour-deep-link:focus,\s*\.tour-video-download a:hover,\s*\.tour-video-download a:focus\s*\{[^}]*color:\s*var\(--oasis-dark-link\)",
        r"\.tour-cta:focus-visible\s*\{[^}]*outline:\s*3px solid var\(--oasis-focus\)",
    ):
        if not re.search(selector_contract, styles, flags=re.DOTALL):
            raise SystemExit(
                f"accessible interaction-state rule is missing: {selector_contract}"
            )

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
    if not (
        demo.get("recorded")
        and demo.get("live_service") is False
        and demo.get("path") == "explore.html"
        and demo.get("tour_count") == 2
        and demo.get("data_classification") == "declared per tour"
    ):
        raise SystemExit("publication demonstration scope is not explicit")
    if len(publication.get("demo_media", [])) != 27:
        raise SystemExit("publication media inventory is incomplete")
    capture_manifests = publication.get("capture_manifests", [])
    if (
        len(capture_manifests) != 2
        or {item.get("tour_id") for item in capture_manifests}
        != {"cli-tui", "maples"}
    ):
        raise SystemExit("publication capture-manifest inventory is incomplete")
    if publication.get("tour_overview") != "explore.html":
        raise SystemExit("publication tour overview is missing")
    tour_rows = publication.get("tours", [])
    tours = {item.get("id"): item for item in tour_rows}
    if len(tours) != len(tour_rows):
        raise SystemExit("publication tour catalog contains duplicate ids")
    if set(tours) != {"cli-tui", "maples"}:
        raise SystemExit("publication tour catalog is incomplete")
    if not tours["cli-tui"].get("recorded") or tours["cli-tui"].get("path") != "tui.html":
        raise SystemExit("publication CLI/TUI tour record is invalid")
    maples_tour = tours["maples"]
    if (
        maples_tour.get("recorded") is not True
        or maples_tour.get("status") != "recorded"
        or maples_tour.get("path") != "maples.html"
        or maples_tour.get("live_service") is not False
        or maples_tour.get("synthetic_or_sanitized") is not True
        or maples_tour.get("data_classification") != "synthetic-coded"
        or maples_tour.get("real_person_data") is not False
        or maples_tour.get("visitor_network_calls") is not False
        or maples_tour.get("grading_pipeline_invoked") is not False
        or maples_tour.get("provider_calls") != 0
        or maples_tour.get("paid_spend_usd") != 0
        or maples_tour.get("capture_state") != "verified-offline"
        or maples_tour.get("source_head_sha")
        != "90031150529bbfa1a3de4f5769039fb91940ed08"
        or len(maples_tour.get("media_assets", [])) != 7
    ):
        raise SystemExit("publication MAPLES recorded-tour contract is invalid")
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
    required_pages = ("index.html", "explore.html", "tui.html", "maples.html")
    missing_pages = [name for name in required_pages if not (OUTPUT / name).is_file()]
    if missing_pages:
        raise SystemExit(f"rendered site is incomplete; missing={missing_pages}")
    check_references()
    check_media_manifest()
    check_maples_media_manifest()
    check_checksums()
    check_contract()
    print("OASIS project site checks: PASS")


if __name__ == "__main__":
    main()
