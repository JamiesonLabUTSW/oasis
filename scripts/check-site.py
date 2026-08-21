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


class RubricGuideStructureParser(HTMLParser):
    """Inspect the authored rubric-guide subtree without executing JavaScript."""

    VOID_ELEMENTS = {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
    MEDIA_ELEMENTS = {"audio", "embed", "iframe", "img", "object", "picture", "video"}

    def __init__(self) -> None:
        super().__init__()
        self.guide_count = 0
        self.depth = 0
        self.tablists: list[dict[str, str]] = []
        self.tabs: list[dict[str, str]] = []
        self.panels: list[dict[str, str]] = []
        self.media: list[str] = []
        self.choices: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = {key: value or "" for key, value in attrs}
        starts_guide = values.get("id") == "rubric-guide" and "data-rubric-guide" in values
        inside = self.depth > 0 or starts_guide
        if starts_guide:
            self.guide_count += 1
            self.depth = 1
        elif self.depth > 0 and tag not in self.VOID_ELEMENTS:
            self.depth += 1
        if not inside:
            return
        if values.get("role") == "tablist":
            self.tablists.append(values)
        if "data-rubric-tab" in values:
            self.tabs.append(values)
        if "data-rubric-panel" in values:
            self.panels.append(values)
        if "data-rubric-choice" in values:
            self.choices.append(values)
        if tag in self.MEDIA_ELEMENTS:
            self.media.append(tag)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, _tag: str) -> None:
        if self.depth > 0:
            self.depth -= 1


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


def parse_candle_static_webp(path: Path) -> list[str]:
    data = path.read_bytes()
    relative = path.relative_to(OUTPUT)
    if len(data) < 12 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise SystemExit(f"invalid Candle WebP container: {relative}")
    if struct.unpack_from("<I", data, 4)[0] + 8 != len(data):
        raise SystemExit(f"Candle WebP RIFF length mismatch: {relative}")

    chunks = []
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise SystemExit(f"truncated Candle WebP chunk header: {relative}")
        name = data[offset : offset + 4].decode("ascii", errors="strict")
        size = struct.unpack_from("<I", data, offset + 4)[0]
        offset += 8
        if offset + size > len(data):
            raise SystemExit(f"truncated Candle WebP chunk: {relative}")
        chunks.append(name)
        offset += size + (size % 2)
    if offset != len(data):
        raise SystemExit(f"trailing Candle WebP data: {relative}")

    forbidden = {"EXIF", "XMP ", "ICCP", "ANIM", "ANMF"}
    image_chunks = {"VP8 ", "VP8L"}.intersection(chunks)
    if forbidden.intersection(chunks) or len(image_chunks) != 1:
        raise SystemExit(
            f"Candle poster is not a metadata-free static WebP: "
            f"{relative} chunks={chunks}"
        )
    return chunks


def check_candle_media_manifest() -> dict[str, object]:
    manifest_path = OUTPUT / "assets" / "candle" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_top_level = {
        "schema_version",
        "generated_at",
        "scenario",
        "application",
        "execution_boundary",
        "privacy_review",
        "content_review",
        "delivery",
        "assets",
    }
    if set(manifest) != expected_top_level:
        raise SystemExit(
            "Candle media manifest top-level contract is invalid: "
            f"{sorted(manifest)}"
        )
    if manifest.get("schema_version") != "oasis.candle-cli-mcp-site-media.v1":
        raise SystemExit("Candle media manifest schema is invalid")
    if manifest.get("generated_at") != "2026-08-20T21:32:18Z":
        raise SystemExit("Candle media manifest timestamp is invalid")

    scenario = manifest.get("scenario", {})
    if (
        set(scenario)
        != {
            "id",
            "title",
            "data_classification",
            "description",
            "synthetic_only",
            "coded_ids",
            "real_person_data",
            "station",
            "rubric_criteria",
        }
        or scenario.get("id") != "candle-making-files-to-evidence-v1"
        or scenario.get("title")
        != "Candle Making: From files to verified evidence"
        or scenario.get("data_classification") != "synthetic-coded"
        or scenario.get("synthetic_only") is not True
        or scenario.get("coded_ids") != ["DEMO-001", "DEMO-002", "DEMO-003"]
        or scenario.get("real_person_data") is not False
        or scenario.get("station") != "CandleMaking"
        or scenario.get("rubric_criteria") != 3
        or scenario.get("description")
        != (
            "Newly authored public fixture notes exercise standalone OASIS CLI "
            "and MCP paths without learner, patient, customer, or other "
            "real-person data."
        )
    ):
        raise SystemExit("Candle scenario provenance or privacy scope is invalid")

    source_sha = "db2861fdc79aa3bddeaed949c1282e068e7f4eb9"
    application = manifest.get("application", {})
    binaries = application.get("binaries", [])
    if (
        set(application)
        != {
            "source_repository_public",
            "source_revision",
            "tree_clean",
            "module_identity",
            "binaries",
        }
        or application.get("source_repository_public") is not False
        or application.get("source_revision") != source_sha
        or application.get("tree_clean") is not True
        or application.get("module_identity")
        != "github.com/JamiesonLabUTSW/oasis"
        or not isinstance(binaries, list)
        or len(binaries) != 2
    ):
        raise SystemExit("Candle source or application identity is invalid")
    binaries_by_name = {
        row.get("name"): row for row in binaries if isinstance(row, dict)
    }
    if set(binaries_by_name) != {"oasis", "oasis-mcp"}:
        raise SystemExit("Candle binary inventory is invalid")
    expected_binary_versions = {"oasis": "0.1.0-mvp", "oasis-mcp": None}
    expected_binary_modules = {
        "oasis": "github.com/JamiesonLabUTSW/oasis/oasis-go/cmd/oasis",
        "oasis-mcp": "github.com/JamiesonLabUTSW/oasis/oasis-go/cmd/oasis-mcp",
    }
    expected_binary_hashes = {
        "oasis": "c22077c0929a2ab457f72b2e8bf07f0eb58813f7701f906da2622c3e286a56f4",
        "oasis-mcp": "1fd230309bcb87fee1ed77c73c59dd4f310ad9523e74662e3970d76970f980c4",
    }
    for name, row in binaries_by_name.items():
        expected_keys = {
            "name",
            "version",
            "module",
            "vcs_revision",
            "vcs_modified",
            "sha256",
        }
        if name == "oasis-mcp":
            expected_keys.update({"server_name", "protocol_version"})
        if (
            set(row) != expected_keys
            or row.get("name") != name
            or row.get("version") != expected_binary_versions[name]
            or row.get("module") != expected_binary_modules[name]
            or row.get("vcs_revision") != source_sha
            or row.get("vcs_modified") is not False
            or row.get("sha256") != expected_binary_hashes[name]
            or (
                name == "oasis-mcp"
                and (
                    row.get("server_name") != "oasis-go-mcp"
                    or row.get("protocol_version") != "2024-11-05"
                )
            )
        ):
            raise SystemExit(f"Candle binary identity is invalid: {name}")

    boundary = manifest.get("execution_boundary", {})
    sample = boundary.get("sample", {})
    full_run = boundary.get("cli_full_run", {})
    mcp_run = boundary.get("mcp_cache_backed_run", {})
    campaign = boundary.get("campaign_total", {})
    cli_integrity = boundary.get("cli_integrity", {})
    mcp_integrity = boundary.get("mcp_integrity", {})
    if (
        set(boundary)
        != {
            "provider_adapter",
            "fixture_model",
            "loopback_only",
            "capture_external_provider_calls",
            "visitor_calls_external_provider",
            "paid_usd",
            "plan_provider_requests",
            "plan_rough_estimated_cost_usd",
            "sample",
            "cli_full_run",
            "mcp_cache_backed_run",
            "campaign_total",
            "cli_integrity",
            "mcp_integrity",
        }
        or set(sample)
        != {
            "loopback_requests",
            "results",
            "item_scores",
            "fixture_reported_tokens",
            "oasis_estimated_cost_usd",
        }
        or set(full_run)
        != {
            "loopback_requests",
            "cache_hits",
            "results",
            "item_scores",
            "fixture_reported_tokens",
            "oasis_estimated_cost_usd",
        }
        or set(mcp_run)
        != {
            "cache_hits",
            "total_calls",
            "new_loopback_requests",
            "new_fixture_reported_tokens",
            "new_estimated_cost_usd",
        }
        or set(campaign)
        != {
            "loopback_requests",
            "results",
            "item_scores",
            "fixture_reported_tokens",
            "oasis_estimated_cost_usd",
        }
        or boundary.get("provider_adapter") != "openai-compatible"
        or boundary.get("fixture_model") != "candle-fixture-v1"
        or boundary.get("loopback_only") is not True
        or boundary.get("capture_external_provider_calls") != 0
        or boundary.get("visitor_calls_external_provider") is not False
        or boundary.get("paid_usd") != 0
        or boundary.get("plan_provider_requests") != 0
        or boundary.get("plan_rough_estimated_cost_usd") != 0.010096
        or sample.get("loopback_requests") != 1
        or sample.get("results") != 1
        or sample.get("item_scores") != 3
        or sample.get("fixture_reported_tokens") != 360
        or sample.get("oasis_estimated_cost_usd") != 0.00084
        or full_run.get("loopback_requests") != 3
        or full_run.get("cache_hits") != 0
        or full_run.get("results") != 3
        or full_run.get("item_scores") != 9
        or full_run.get("fixture_reported_tokens") != 1080
        or full_run.get("oasis_estimated_cost_usd") != 0.00252
        or mcp_run.get("cache_hits") != 3
        or mcp_run.get("total_calls") != 3
        or mcp_run.get("new_loopback_requests") != 0
        or mcp_run.get("new_fixture_reported_tokens") != 0
        or mcp_run.get("new_estimated_cost_usd") != 0
        or campaign.get("loopback_requests") != 4
        or campaign.get("results") != 4
        or campaign.get("item_scores") != 12
        or campaign.get("fixture_reported_tokens") != 1440
        or campaign.get("oasis_estimated_cost_usd") != 0.00336
        or cli_integrity
        != {"status": "verified", "verified": 22, "total": 22, "failed": 0}
        or mcp_integrity
        != {"status": "verified", "verified": 21, "total": 21, "failed": 0}
    ):
        raise SystemExit("Candle execution, accounting, cache, or evidence boundary is invalid")
    if "encounters_graded" in json.dumps(manifest, sort_keys=True):
        raise SystemExit("Candle public manifest publishes the known-buggy sample counter")

    privacy = manifest.get("privacy_review", {})
    path_scan = privacy.get("path_scan", {})
    ocr = privacy.get("ocr", {})
    manual = privacy.get("manual_review", {})
    if (
        set(privacy)
        != {"status", "forbidden_patterns", "path_scan", "ocr", "manual_review"}
        or set(path_scan)
        != {
            "asset_files_scanned",
            "private_path_matches",
            "credential_matches",
            "email_matches",
        }
        or set(ocr)
        != {
            "engine",
            "poster_files_scanned",
            "motion_frames_scanned",
            "files_scanned",
            "errors",
            "private_path_matches",
            "credential_matches",
            "email_matches",
            "real_person_data_term_matches",
        }
        or set(manual)
        != {
            "status",
            "reviewer",
            "poster_files_reviewed",
            "motion_frames_reviewed",
            "contact_sheets_reviewed",
            "findings",
        }
        or privacy.get("status") != "passed"
        or privacy.get("forbidden_patterns")
        != [
            "mac_user_home_path",
            "linux_user_home_path",
            "cluster_storage_path",
            "local_account_identifier",
            "api_credential_shape",
            "email_address_shape",
            "real_person_data_terms",
        ]
        or path_scan
        != {
            "asset_files_scanned": 11,
            "private_path_matches": 0,
            "credential_matches": 0,
            "email_matches": 0,
        }
        or ocr
        != {
            "engine": "Apple Vision VNRecognizeTextRequest",
            "poster_files_scanned": 8,
            "motion_frames_scanned": 58,
            "files_scanned": 66,
            "errors": 0,
            "private_path_matches": 0,
            "credential_matches": 0,
            "email_matches": 0,
            "real_person_data_term_matches": 0,
        }
        or manual
        != {
            "status": "passed",
            "reviewer": "Codex visual QA",
            "poster_files_reviewed": 8,
            "motion_frames_reviewed": 58,
            "contact_sheets_reviewed": 6,
            "findings": 0,
        }
    ):
        raise SystemExit("Candle media privacy, OCR, path, or manual review is incomplete")

    content = manifest.get("content_review", {})
    if (
        set(content)
        != {
            "status",
            "sample_counter_field_published",
            "mcp_described_as_replay",
            "fixture_scores_labeled",
            "costs_labeled_as_estimates",
            "mcp_tool_names_exact",
            "mcp_arguments_rendered_separately",
            "standalone_intake_described_as_managed_upload",
            "summary_item_rows_labeled_as_scored_items",
            "cache_hits_described_without_payload_integrity_claim",
            "capture_source_hashes_recorded",
        }
        or content.get("status") != "passed"
        or content.get("sample_counter_field_published") is not False
        or content.get("mcp_described_as_replay") is not False
        or content.get("fixture_scores_labeled") is not True
        or content.get("costs_labeled_as_estimates") is not True
        or content.get("mcp_tool_names_exact") is not True
        or content.get("mcp_arguments_rendered_separately") is not True
        or content.get("standalone_intake_described_as_managed_upload") is not False
        or content.get("summary_item_rows_labeled_as_scored_items") is not True
        or content.get("cache_hits_described_without_payload_integrity_claim")
        is not True
        or content.get("capture_source_hashes_recorded") is not True
    ):
        raise SystemExit("Candle media truth-language review is incomplete")

    delivery = manifest.get("delivery", {})
    codecs = delivery.get("codecs", {})
    if (
        set(delivery)
        != {
            "capture_tool",
            "capture_tool_version",
            "master_width",
            "master_height",
            "terminal_columns",
            "terminal_rows",
            "source_tape",
            "motion_duration_seconds",
            "motion_has_audio",
            "poster_width",
            "poster_height",
            "motion_width",
            "motion_height",
            "gif_width",
            "gif_height",
            "codecs",
            "asset_count",
            "total_bytes",
            "poster_max_bytes",
            "webm_max_bytes",
            "mp4_max_bytes",
            "gif_max_bytes",
            "total_max_bytes",
            "capture_sources",
        }
        or delivery.get("capture_tool") != "VHS"
        or delivery.get("capture_tool_version") != "0.10.0"
        or delivery.get("master_width") != 1200
        or delivery.get("master_height") != 720
        or delivery.get("terminal_columns") != 102
        or delivery.get("terminal_rows") != 27
        or delivery.get("source_tape") != "capture/candle-overview.tape"
        or delivery.get("motion_duration_seconds", 0) <= 0
        or delivery.get("motion_has_audio") is not False
        or delivery.get("poster_width") != 1200
        or delivery.get("poster_height") != 720
        or delivery.get("motion_width") != 960
        or delivery.get("motion_height") != 576
        or delivery.get("gif_width") != 720
        or delivery.get("gif_height") != 432
        or abs(delivery.get("motion_duration_seconds", 0) - 58.333) > 0.005
        or codecs
        != {
            "webm": {
                "container": "matroska,webm",
                "video_codec": "vp9",
                "pixel_format": "yuv420p",
            },
            "mp4": {
                "container": "mov,mp4,m4a,3gp,3g2,mj2",
                "video_codec": "h264",
                "pixel_format": "yuv420p",
            },
            "gif": {
                "container": "gif",
                "video_codec": "gif",
                "pixel_format": "bgra",
            },
        }
        or delivery.get("asset_count") != 11
        or delivery.get("total_bytes") != 3208781
        or delivery.get("poster_max_bytes") != 153600
        or delivery.get("webm_max_bytes") != 2097152
        or delivery.get("mp4_max_bytes") != 2621440
        or delivery.get("gif_max_bytes") != 1572864
        or delivery.get("total_max_bytes") != 6815744
        or delivery.get("capture_sources")
        != {
            "tape": {
                "name": "candle-overview.tape",
                "sha256": (
                    "ccb0b4994dd8f8e7d8ee33f8eecac6be793facd4c9f299b291e89cd6dfbe588c"
                ),
                "private_evidence_archived": True,
            },
            "mcp_driver": {
                "name": "candle_mcp_demo.py",
                "sha256": (
                    "381cb2f154f00a93ab11980096f9648a91c2e6ec03065296223cea3822a0284e"
                ),
                "private_evidence_archived": True,
            },
        }
    ):
        raise SystemExit("Candle delivery geometry, codec, or capture contract is invalid")

    poster_scenes = [
        "inputs",
        "data",
        "rubric",
        "plan",
        "sample",
        "run",
        "mcp",
        "evidence",
    ]
    expected_files = [
        f"candle-{index:02d}-{scene}-poster.webp"
        for index, scene in enumerate(poster_scenes, start=1)
    ] + ["candle-overview.webm", "candle-overview.mp4", "candle-overview.gif"]
    expected_paths = [f"assets/candle/{name}" for name in expected_files]
    expected_asset_locks = [
        (
            "candle-inputs-poster",
            70524,
            "5c40e49694aa853f484a637e1376aa6e6265813c15f2702370d14b214671e18e",
        ),
        (
            "candle-data-poster",
            83472,
            "15a45c4fca1b9548bd557ed5b795dd31ace3714ad963ec286394009e2e787485",
        ),
        (
            "candle-rubric-poster",
            43806,
            "b6bc1af91d3fedc373a6ce9eb4ab484b0a76413a3fa10dcb8f7e61dc8f1c30bf",
        ),
        (
            "candle-plan-poster",
            57650,
            "69097357abcd9e0399f1c2271b77aabf18bf28cdb3c96fd8a7e57833fe7e4c72",
        ),
        (
            "candle-sample-poster",
            70070,
            "4e01fd08c11b869779dd7e9c48994f1ae4b129c203c5065635de1572d1a781bf",
        ),
        (
            "candle-run-poster",
            67242,
            "d2e5d9ae252e6fdee58e006711ea98ef3e158219d7fa42a030fea269cf625ceb",
        ),
        (
            "candle-mcp-poster",
            63550,
            "5badc275b173d7ca85c4aab3bf5fad9cef5732c6ba286a0dbd5c8d9223a2ad55",
        ),
        (
            "candle-evidence-poster",
            102430,
            "ae3a0a1e567aa05d11bb46bfca4f227574f75ba747ea04b31a06cbbd1a6392bc",
        ),
        (
            "candle-overview-webm",
            803675,
            "5697d57ca69a050aa7681ec8c9ee080065adb362b2f86394402667634612b4a2",
        ),
        (
            "candle-overview-mp4",
            845807,
            "dafe6db9e7f3b005bfedfe07158148a6b8de6bfc2fd23f876e766c84b8aa3085",
        ),
        (
            "candle-overview-gif",
            1000555,
            "43cd4a9b7805c299f18cdc3e3a1ddb068cc64c95072bdada59cd07313288b0c4",
        ),
    ]
    expected_alts = [
        "Terminal listing three coded synthetic Candle Making notes and the local rubric before OASIS reads them.",
        "OASIS CLI data validation and scan results for three coded synthetic Candle Making notes.",
        "OASIS CLI strict rubric check passing for the three-criterion Candle Making rubric.",
        "OASIS CLI dry-run plan showing three encounters, three criteria, three planned calls, the candle-fixture-v1 model, and $0 paid.",
        "OASIS CLI sample assessment of one coded synthetic Candle Making note through the loopback fixture.",
        "Completed OASIS CLI run showing three coded encounters and nine fixture scores.",
        "Recorded MCP wire transcript showing a fresh cache-backed OASIS run with three cache hits and no new fixture requests.",
        "OASIS evidence verification reporting 22 of 22 hashes valid for the recorded Candle Making CLI run.",
        "Recorded terminal overview of the OASIS Candle Making CLI and MCP workflow from synthetic files through verified evidence.",
        "Recorded terminal overview of the OASIS Candle Making CLI and MCP workflow from synthetic files through verified evidence.",
        "Recorded terminal overview of the OASIS Candle Making CLI and MCP workflow from synthetic files through verified evidence.",
    ]
    assets = manifest.get("assets", [])
    if (
        not isinstance(assets, list)
        or len(assets) != 11
        or [row.get("order") for row in assets if isinstance(row, dict)]
        != list(range(1, 12))
        or [row.get("path") for row in assets if isinstance(row, dict)]
        != expected_paths
        or [
            (row.get("id"), row.get("bytes"), row.get("sha256"))
            for row in assets
            if isinstance(row, dict)
        ]
        != expected_asset_locks
        or [row.get("alt") for row in assets if isinstance(row, dict)]
        != expected_alts
    ):
        raise SystemExit("Candle media asset inventory is incomplete or out of order")

    total_bytes = 0
    expected_asset_keys = {
        "order",
        "id",
        "scene",
        "role",
        "path",
        "alt",
        "format",
        "bytes",
        "sha256",
        "width",
        "height",
        "duration_seconds",
        "container",
        "video_codec",
        "pixel_format",
        "audio_streams",
    }
    for index, row in enumerate(assets):
        if not isinstance(row, dict):
            raise SystemExit("Candle media asset row is invalid")
        path_value = row.get("path", "")
        path = OUTPUT / path_value
        if not path.is_file():
            raise SystemExit(f"Candle media asset is missing: {path_value}")
        if (
            set(row) != expected_asset_keys
            or row.get("bytes") != path.stat().st_size
            or row.get("sha256") != digest(path)
            or row.get("audio_streams") != 0
            or not isinstance(row.get("alt"), str)
            or not row["alt"].strip()
        ):
            raise SystemExit(f"Candle media asset metadata mismatch: {path_value}")

        if index < 8:
            if (
                row.get("scene") != poster_scenes[index]
                or row.get("role") != "poster"
                or row.get("format") != "webp"
                or row.get("width") != delivery["poster_width"]
                or row.get("height") != delivery["poster_height"]
                or row.get("duration_seconds") is not None
                or row.get("container") != "webp_pipe"
                or row.get("video_codec") != "webp"
                or row.get("pixel_format") != "yuv420p"
                or path.stat().st_size > delivery["poster_max_bytes"]
            ):
                raise SystemExit(f"Candle poster contract is invalid: {path_value}")
            if parse_candle_static_webp(path) != ["VP8 "]:
                raise SystemExit(f"Candle poster codec is invalid: {path_value}")
        else:
            media_format = expected_files[index].rsplit(".", 1)[1]
            duration = row.get("duration_seconds")
            expected_width = (
                delivery["gif_width"]
                if media_format == "gif"
                else delivery["motion_width"]
            )
            expected_height = (
                delivery["gif_height"]
                if media_format == "gif"
                else delivery["motion_height"]
            )
            expected_containers = {
                "webm": "matroska,webm",
                "mp4": "mov,mp4,m4a,3gp,3g2,mj2",
                "gif": "gif",
            }
            expected_pixel_formats = {
                "webm": "yuv420p",
                "mp4": "yuv420p",
                "gif": "bgra",
            }
            expected_durations = {
                "webm": 58.334,
                "mp4": 58.333333,
                "gif": 58.34,
            }
            codec = codecs[media_format]
            if (
                row.get("scene") != "overview"
                or row.get("role") != "motion"
                or row.get("format") != media_format
                or row.get("width") != expected_width
                or row.get("height") != expected_height
                or not isinstance(duration, (int, float))
                or abs(duration - expected_durations[media_format]) > 0.001
                or row.get("container") != expected_containers[media_format]
                or row.get("container") != codec["container"]
                or row.get("video_codec") != codec["video_codec"]
                or row.get("pixel_format") != expected_pixel_formats[media_format]
                or row.get("pixel_format") != codec["pixel_format"]
                or path.stat().st_size > delivery[f"{media_format}_max_bytes"]
            ):
                raise SystemExit(f"Candle motion-media contract is invalid: {path_value}")
        total_bytes += path.stat().st_size

    if (
        total_bytes != delivery.get("total_bytes")
        or total_bytes > delivery.get("total_max_bytes", 0)
    ):
        raise SystemExit("Candle delivery byte total does not match its assets")
    return manifest


def check_elephant_media_manifest() -> dict[str, object]:
    manifest_path = OUTPUT / "assets" / "elephant" / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(
            "Elephant capture is not ready: verified assets/elephant/manifest.json is missing"
        )
    expected_manifest_sha256 = (
        "4ca212bb6290593603459f345c3344d398963a90e9c81dc37ed3d80e5cee6504"
    )
    if digest(manifest_path) != expected_manifest_sha256:
        raise SystemExit("Elephant capture manifest does not match the sealed review")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    expected_top_level = {
        "schema_version",
        "generated_at",
        "scenario",
        "fixture",
        "application",
        "execution_boundary",
        "evidence",
        "privacy_review",
        "content_review",
        "delivery",
        "assets",
    }
    if set(manifest) != expected_top_level:
        raise SystemExit(
            "Elephant media manifest top-level contract is invalid: "
            f"{sorted(manifest)}"
        )
    if manifest.get("schema_version") != "oasis.elephant-ingestion-site-media.v1":
        raise SystemExit("Elephant media manifest schema is invalid")
    generated_at = manifest.get("generated_at")
    if not isinstance(generated_at, str) or not re.fullmatch(
        r"2026-08-21T\d{2}:\d{2}:\d{2}Z", generated_at
    ):
        raise SystemExit("Elephant media manifest timestamp is invalid")

    scenario = manifest.get("scenario", {})
    if (
        set(scenario)
        != {
            "id",
            "title",
            "data_classification",
            "description",
            "synthetic_only",
            "real_person_data",
            "coded_ids",
            "reserved_email_domain",
            "cohort",
            "record_count",
            "file_count",
            "file_type",
        }
        or scenario.get("id") != "elephant-agent-assisted-candle-v1"
        or scenario.get("title")
        != "Elephant ingestion: From a folder to verified records"
        or scenario.get("data_classification") != "synthetic-coded"
        or not isinstance(scenario.get("description"), str)
        or not scenario["description"].strip()
        or scenario.get("synthetic_only") is not True
        or scenario.get("real_person_data") is not False
        or scenario.get("coded_ids") != ["DEMO-001", "DEMO-002", "DEMO-003"]
        or scenario.get("reserved_email_domain") != "example.com"
        or scenario.get("cohort") != "OASIS Candle Demo"
        or scenario.get("record_count") != 3
        or scenario.get("file_count") != 3
        or scenario.get("file_type") != "notes_txt"
    ):
        raise SystemExit("Elephant scenario provenance or privacy scope is invalid")

    fixture = manifest.get("fixture", {})
    fixture_manifest = fixture.get("manifest", {})
    fixture_files = fixture.get("files", [])
    if (
        set(fixture)
        != {
            "manifest",
            "files",
            "file_set_digest_algorithm",
            "file_set_canonicalization",
            "file_set_sha256",
        }
        or set(fixture_manifest)
        != {"name", "bytes", "sha256", "columns", "row_count"}
        or fixture_manifest.get("name") != "manifest.csv"
        or not isinstance(fixture_manifest.get("bytes"), int)
        or fixture_manifest["bytes"] <= 0
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(fixture_manifest.get("sha256", ""))
        )
        or fixture_manifest.get("columns")
        != [
            "cohort_name",
            "learner_name",
            "learner_email",
            "activity",
            "case_name",
            "date",
            "room",
            "file_path",
            "file_type",
        ]
        or fixture_manifest.get("row_count") != 3
        or fixture.get("file_set_digest_algorithm") != "sha256"
        or fixture.get("file_set_canonicalization")
        != "relative-path-tab-bytes-tab-sha256-lf"
        or not re.fullmatch(r"[0-9a-f]{64}", str(fixture.get("file_set_sha256", "")))
    ):
        raise SystemExit("Elephant fixture manifest or file-set identity is invalid")
    expected_fixture_paths = [
        "DEMO-001/note.txt",
        "DEMO-002/note.txt",
        "DEMO-003/note.txt",
    ]
    if (
        not isinstance(fixture_files, list)
        or len(fixture_files) != 3
        or [item.get("relative_path") for item in fixture_files if isinstance(item, dict)]
        != expected_fixture_paths
    ):
        raise SystemExit("Elephant fixture file inventory is incomplete or out of order")
    for item in fixture_files:
        if (
            not isinstance(item, dict)
            or set(item) != {"relative_path", "bytes", "sha256"}
            or not isinstance(item.get("bytes"), int)
            or item["bytes"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
        ):
            raise SystemExit("Elephant fixture file identity is invalid")

    source_sha = "43b195ac9bf378b7d8a49af3aa9690e78d1d4b8d"
    application = manifest.get("application", {})
    binaries = application.get("binaries", [])
    elephant_runtime = application.get("elephant_runtime", {})
    if (
        set(application)
        != {
            "source_repository_public",
            "source_revision",
            "tree_clean",
            "module_identity",
            "binaries",
            "elephant_runtime",
        }
        or application.get("source_repository_public") is not False
        or application.get("source_revision") != source_sha
        or application.get("tree_clean") is not True
        or application.get("module_identity") != "github.com/JamiesonLabUTSW/oasis"
        or not isinstance(binaries, list)
        or len(binaries) != 2
        or [item.get("name") for item in binaries if isinstance(item, dict)]
        != ["oasis", "oasis-tui"]
        or set(elephant_runtime)
        != {"api_scope", "fresh_storage", "database", "object_storage"}
        or elephant_runtime.get("api_scope") != "local-loopback"
        or elephant_runtime.get("fresh_storage") is not True
        or elephant_runtime.get("database") != "isolated-postgres"
        or elephant_runtime.get("object_storage") != "isolated-minio"
    ):
        raise SystemExit("Elephant capture source or local runtime identity is invalid")
    binary_keys = {
        "name",
        "version",
        "module",
        "sha256",
    }
    for binary in binaries:
        binary_version = binary.get("version") if isinstance(binary, dict) else None
        if (
            not isinstance(binary, dict)
            or set(binary) != binary_keys
            or (
                binary.get("name") == "oasis"
                and (
                    not isinstance(binary_version, str)
                    or not binary_version.strip()
                )
            )
            or (
                binary.get("name") == "oasis-tui"
                and binary_version is not None
                and (
                    not isinstance(binary_version, str)
                    or not binary_version.strip()
                )
            )
            or not isinstance(binary.get("module"), str)
            or not binary["module"].strip()
            or not isinstance(binary.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", binary["sha256"])
        ):
            raise SystemExit("Elephant binary identity is invalid")

    execution = manifest.get("execution_boundary", {})
    if set(execution) != {
        "agent_exchange",
        "local_checks",
        "approval",
        "import",
        "readback",
        "credentials",
        "visitor_boundary",
    }:
        raise SystemExit("Elephant execution-boundary sections are invalid")
    agent_exchange = execution.get("agent_exchange", {})
    if agent_exchange != {
        "illustrated": True,
        "live": False,
        "named_model_claim": False,
        "external_model_provider_calls": 0,
        "private_reasoning_published": False,
    }:
        raise SystemExit("Elephant agent-exchange truth boundary is invalid")
    local_checks = execution.get("local_checks", {})
    if local_checks != {
        "validation_command": "oasis data validate candle-data",
        "scan_command": (
            "oasis data scan candle-data --hash --summary-only "
            "--fail-on-clarifications --output evidence/scan.json"
        ),
        "scan_json_used_as_import_manifest": False,
        "elephant_api_calls": 0,
    }:
        raise SystemExit("Elephant local-check execution boundary is invalid")
    approval = execution.get("approval", {})
    if approval != {
        "gate_type": "capture-harness",
        "native_cli_prompt": False,
        "target_reviewed": True,
        "manifest_digest_bound": True,
        "file_set_digest_bound": True,
        "changed_input_expires_approval": True,
    }:
        raise SystemExit("Elephant approval boundary is invalid")
    import_boundary = execution.get("import", {})
    if import_boundary != {
        "dry_run_command": (
            "oasis data import manifest.csv --data-dir candle-data --dry-run"
        ),
        "import_command": "oasis data import manifest.csv --data-dir candle-data",
        "idempotency_key_used": False,
        "dry_run_api_calls": 0,
        "rows_total": 3,
        "rows_failed": 0,
        "groups_expected": 1,
        "records_expected": 3,
        "files_expected": 3,
        "atomic": False,
        "resumable": False,
        "durable_row_receipt": False,
        "unchanged_input_safe_to_retry": True,
        "changed_input_requires_review": True,
    }:
        raise SystemExit("Elephant import execution boundary is invalid")
    readback = execution.get("readback", {})
    if readback != {
        "cli_json_used": True,
        "tui_groups_view": True,
        "tui_encounters_view": True,
        "tui_files_is_grouped_summary": True,
        "original_filenames_returned": False,
        "stored_file_metadata_verified_via_cli": True,
    }:
        raise SystemExit("Elephant read-back boundary is invalid")
    credentials = execution.get("credentials", {})
    if credentials != {
        "write_key_scope": "scoped-write",
        "write_key_source": "private-environment-file",
        "write_key_in_argv": False,
        "write_key_published": False,
        "readback_key_scope": "read-only",
        "separate_keys": True,
    }:
        raise SystemExit("Elephant credential boundary is invalid")
    visitor_boundary = execution.get("visitor_boundary", {})
    if visitor_boundary != {
        "live_service": False,
        "visitor_elephant_calls": False,
        "visitor_model_calls": False,
    }:
        raise SystemExit("Elephant visitor execution boundary is invalid")

    evidence = manifest.get("evidence", {})
    evidence_items = evidence.get("items", [])
    evidence_counts = evidence.get("counts", {})
    if (
        set(evidence)
        != {
            "status",
            "raw_logs_published",
            "credentials_present",
            "private_paths_present",
            "item_count",
            "items",
            "counts",
        }
        or evidence.get("status") != "archived-private"
        or evidence.get("raw_logs_published") is not False
        or evidence.get("credentials_present") is not False
        or evidence.get("private_paths_present") is not False
        or evidence.get("item_count") != 5
        or evidence_counts
        != {
            "validated_files": 3,
            "scan_records": 3,
            "dry_run_rows": 3,
            "import_rows": 3,
            "import_failed_rows": 0,
            "readback_file_groups": 3,
            "readback_files": 3,
        }
    ):
        raise SystemExit("Elephant archived evidence summary is invalid")
    expected_evidence_ids = [
        "local-validate",
        "local-scan",
        "import-preview",
        "import-run",
        "file-readback",
    ]
    if (
        not isinstance(evidence_items, list)
        or len(evidence_items) != 5
        or [item.get("id") for item in evidence_items if isinstance(item, dict)]
        != expected_evidence_ids
    ):
        raise SystemExit("Elephant archived evidence inventory is incomplete or out of order")
    for item in evidence_items:
        name = item.get("name") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or set(item)
            != {
                "id",
                "name",
                "bytes",
                "sha256",
                "sanitized",
                "archived_private",
                "published",
            }
            or not isinstance(name, str)
            or not name
            or "/" in name
            or "\\" in name
            or not isinstance(item.get("bytes"), int)
            or item["bytes"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("sha256", "")))
            or item.get("sanitized") is not True
            or item.get("archived_private") is not True
            or item.get("published") is not False
        ):
            raise SystemExit("Elephant archived evidence identity is invalid")

    privacy = manifest.get("privacy_review", {})
    if (
        set(privacy)
        != {
            "status",
            "asset_files_scanned",
            "posters_ocr_reviewed",
            "motion_frames_ocr_reviewed",
            "posters_manual_reviewed",
            "motion_frames_manual_reviewed",
            "ocr_errors",
            "sensitive_hits",
            "real_person_data_visible",
            "allowed_emails",
            "all_passed",
        }
        or privacy.get("status") != "passed"
        or privacy.get("asset_files_scanned") != 11
        or privacy.get("posters_ocr_reviewed") != 9
        or not isinstance(privacy.get("motion_frames_ocr_reviewed"), int)
        or privacy["motion_frames_ocr_reviewed"] <= 0
        or privacy.get("posters_manual_reviewed") != 9
        or not isinstance(privacy.get("motion_frames_manual_reviewed"), int)
        or privacy["motion_frames_manual_reviewed"] <= 0
        or privacy.get("ocr_errors") != 0
        or privacy.get("sensitive_hits") != 0
        or privacy.get("real_person_data_visible") is not False
        or privacy.get("allowed_emails")
        != [
            "demo-001@example.com",
            "demo-002@example.com",
            "demo-003@example.com",
        ]
        or privacy.get("all_passed") is not True
    ):
        raise SystemExit("Elephant media privacy review is incomplete")

    content_review = manifest.get("content_review", {})
    if content_review != {
        "agent_exchange_labeled_illustrated": True,
        "scan_json_called_import_manifest": False,
        "native_cli_approval_claimed": False,
        "native_resume_claimed": False,
        "atomic_import_claimed": False,
        "tui_groups_called_datasets": False,
        "tui_files_called_individual_file_rows": False,
        "original_filenames_claimed": False,
        "secrets_published": False,
        "private_paths_published": False,
        "visitor_network_calls": False,
        "source_hashes_recorded": True,
        "fixture_digests_recorded": True,
        "private_evidence_hashes_recorded": True,
    }:
        raise SystemExit("Elephant media content review is incomplete")

    delivery = manifest.get("delivery", {})
    delivery_keys = {
        "capture_tool",
        "capture_tool_version",
        "poster_width",
        "poster_height",
        "motion_width",
        "motion_height",
        "motion_duration_seconds",
        "motion_has_audio",
        "codecs",
        "poster_max_bytes",
        "webm_max_bytes",
        "mp4_max_bytes",
        "total_max_bytes",
        "asset_count",
        "total_bytes",
        "capture_sources",
    }
    codecs = delivery.get("codecs", {})
    capture_sources = delivery.get("capture_sources", {})
    duration = delivery.get("motion_duration_seconds")
    if (
        set(delivery) != delivery_keys
        or delivery.get("capture_tool") != "VHS"
        or not isinstance(delivery.get("capture_tool_version"), str)
        or not delivery["capture_tool_version"].strip()
        or delivery.get("poster_width") != 1200
        or delivery.get("poster_height") != 720
        or delivery.get("motion_width") != 960
        or delivery.get("motion_height") != 576
        or not isinstance(duration, (int, float))
        or not 10 <= duration <= 120
        or delivery.get("motion_has_audio") is not False
        or codecs
        != {
            "webm": {
                "container": "matroska,webm",
                "video_codec": "vp9",
                "pixel_format": "yuv420p",
            },
            "mp4": {
                "container": "mov,mp4,m4a,3gp,3g2,mj2",
                "video_codec": "h264",
                "pixel_format": "yuv420p",
            },
        }
        or delivery.get("poster_max_bytes") != 153600
        or delivery.get("webm_max_bytes") != 2097152
        or delivery.get("mp4_max_bytes") != 2621440
        or delivery.get("total_max_bytes") != 6291456
        or delivery.get("asset_count") != 11
        or set(capture_sources) != {"tape"}
        or set(capture_sources.get("tape", {}))
        != {"name", "sha256", "private_evidence_archived"}
        or capture_sources["tape"].get("name") != "elephant-overview.tape"
        or not re.fullmatch(
            r"[0-9a-f]{64}", str(capture_sources["tape"].get("sha256", ""))
        )
        or capture_sources["tape"].get("private_evidence_archived") is not True
    ):
        raise SystemExit("Elephant delivery geometry, codec, or capture contract is invalid")

    poster_scenes = [
        "agent-brief",
        "local-checks",
        "import-preview",
        "human-approval",
        "import-run",
        "dataset",
        "encounters",
        "files",
        "file-details",
    ]
    expected_files = [
        f"elephant-{index:02d}-{scene}-poster.webp"
        for index, scene in enumerate(poster_scenes, start=1)
    ] + ["elephant-overview.webm", "elephant-overview.mp4"]
    expected_paths = [f"assets/elephant/{name}" for name in expected_files]
    expected_ids = [
        f"elephant-{scene}-poster" for scene in poster_scenes
    ] + ["elephant-overview-webm", "elephant-overview-mp4"]
    expected_asset_locks = [
        (
            "elephant-agent-brief-poster",
            43964,
            "bfd4a972b3c6c6ff7345372abbf4743c8fb2c4cec31867e01c7469f7b7fbf3ac",
        ),
        (
            "elephant-local-checks-poster",
            53120,
            "65d8cf86a4d1b1bd48c0cdf76af47380565c23c01ecbe94edc37f9e35fe37739",
        ),
        (
            "elephant-import-preview-poster",
            41976,
            "430954f02f75876d7a54b94e0df231c44b033554692a44301d94bc64e0bc9692",
        ),
        (
            "elephant-human-approval-poster",
            42648,
            "358d6dfb9262fd0ab978a79383c04323d168c6b4e05b905458219bdad6d9a69e",
        ),
        (
            "elephant-import-run-poster",
            59932,
            "8e41632fe3aef0a6da6b7d61453f19a619d965cc3ef270b4d3beb01d5dff60c1",
        ),
        (
            "elephant-dataset-poster",
            31832,
            "40d6bae541bb06e72bf5a3461d18ca28284f412f6ebc4b8f05a497362e36cde0",
        ),
        (
            "elephant-encounters-poster",
            54876,
            "19bd8ba365e3638de5e60eb6ddc55bc9f67a2611aea9827c78d40e3a1e62394c",
        ),
        (
            "elephant-files-poster",
            43846,
            "77638ef597cf3071999cddd35694ed7362b377258fe4e760196df25e638dead5",
        ),
        (
            "elephant-file-details-poster",
            38594,
            "c640b730cb90427405c3690b415cdb1b7f3dbd0280a66b97ca39aee19f297c6a",
        ),
        (
            "elephant-overview-webm",
            868134,
            "d74d5004e05e26cd9977d74ffcc703cd4ad3e9d41ab30d2c7b58f35b897e3bb6",
        ),
        (
            "elephant-overview-mp4",
            498160,
            "f6cd30b6d5be18839522d8b93c9538e4876fc5983cd7fe867cdbbae9fb18143f",
        ),
    ]
    expected_alts = [
        "Illustrated model-neutral agent exchange proposing a three-record Elephant import and stopping before any upload.",
        "OASIS terminal showing local validation and a hashed scan of three synthetic Candle Making notes.",
        "OASIS data import dry run previewing one group, three coded records, and three text-note files with zero API calls.",
        "Terminal approval gate binding the local Elephant target and three-record import to reviewed manifest and file-set fingerprints.",
        "Completed OASIS import into a local Elephant service showing the reviewed synthetic records and zero failed rows.",
        "OASIS TUI Elephant Groups view with the synthetic OASIS Candle Demo group selected.",
        "OASIS TUI Elephant Encounters view listing the three coded Candle Making demo encounters.",
        "OASIS TUI Elephant Files view showing the selected demo encounter and its text-note file count.",
        "Read-only OASIS Elephant JSON output showing coded learners, encounter and file IDs, file types, byte counts, and stored fingerprints.",
        "Recorded local OASIS walkthrough from agent-assisted preparation through Elephant import, TUI browsing, and read-only verification.",
        "Recorded local OASIS walkthrough from agent-assisted preparation through Elephant import, TUI browsing, and read-only verification.",
    ]
    assets = manifest.get("assets", [])
    if (
        not isinstance(assets, list)
        or len(assets) != 11
        or [row.get("order") for row in assets if isinstance(row, dict)]
        != list(range(1, 12))
        or [row.get("id") for row in assets if isinstance(row, dict)] != expected_ids
        or [
            (row.get("id"), row.get("bytes"), row.get("sha256"))
            for row in assets
            if isinstance(row, dict)
        ]
        != expected_asset_locks
        or [row.get("path") for row in assets if isinstance(row, dict)]
        != expected_paths
        or [row.get("alt") for row in assets if isinstance(row, dict)]
        != expected_alts
    ):
        raise SystemExit("Elephant media asset inventory is incomplete or out of order")

    expected_asset_keys = {
        "order",
        "id",
        "scene",
        "role",
        "path",
        "alt",
        "format",
        "bytes",
        "sha256",
        "width",
        "height",
        "duration_seconds",
        "container",
        "video_codec",
        "pixel_format",
        "audio_streams",
    }
    total_bytes = 0
    for index, row in enumerate(assets):
        if not isinstance(row, dict):
            raise SystemExit("Elephant media asset row is invalid")
        path_value = row.get("path", "")
        path = OUTPUT / path_value
        if not path.is_file():
            raise SystemExit(f"Elephant media asset is missing: {path_value}")
        if (
            set(row) != expected_asset_keys
            or row.get("bytes") != path.stat().st_size
            or row.get("sha256") != digest(path)
            or row.get("audio_streams") != 0
            or not isinstance(row.get("sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
        ):
            raise SystemExit(f"Elephant media asset metadata mismatch: {path_value}")
        if index < 9:
            if (
                row.get("scene") != poster_scenes[index]
                or row.get("role") != "poster"
                or row.get("format") != "webp"
                or row.get("width") != 1200
                or row.get("height") != 720
                or row.get("duration_seconds") is not None
                or row.get("container") != "webp_pipe"
                or row.get("video_codec") != "webp"
                or row.get("pixel_format") not in {"yuv420p", "yuva420p"}
                or path.stat().st_size > delivery["poster_max_bytes"]
            ):
                raise SystemExit(f"Elephant poster contract is invalid: {path_value}")
            if parse_candle_static_webp(path) != ["VP8 "]:
                raise SystemExit(f"Elephant poster codec is invalid: {path_value}")
        else:
            media_format = expected_files[index].rsplit(".", 1)[1]
            row_duration = row.get("duration_seconds")
            codec = codecs[media_format]
            if (
                row.get("scene") != "overview"
                or row.get("role") != "motion"
                or row.get("format") != media_format
                or row.get("width") != 960
                or row.get("height") != 576
                or not isinstance(row_duration, (int, float))
                or abs(row_duration - duration) > 0.1
                or row.get("container") != codec["container"]
                or row.get("video_codec") != codec["video_codec"]
                or row.get("pixel_format") != codec["pixel_format"]
                or path.stat().st_size > delivery[f"{media_format}_max_bytes"]
            ):
                raise SystemExit(f"Elephant motion-media contract is invalid: {path_value}")
        total_bytes += path.stat().st_size
    if (
        delivery.get("total_bytes") != total_bytes
        or total_bytes > delivery.get("total_max_bytes", 0)
    ):
        raise SystemExit("Elephant delivery byte total does not match its assets")
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


def check_contract(
    candle_manifest: dict[str, object],
    elephant_manifest: dict[str, object],
) -> None:
    tour_runtime = (OUTPUT / "product-tour.js").read_text(encoding="utf-8")
    for marker in (
        'posterImage.loading = "eager"',
        'posterImage.fetchPriority = "high"',
        'image.fetchPriority = "low"',
        "schedulePosterWarmup(steps[index + 1])",
        "connection.saveData",
        'stage.setAttribute("aria-busy", "true")',
        "activePosterReveal = revealAfterDecode",
        'if (typeof activePosterReveal === "function") activePosterReveal();',
        "posterImage.decode().then(reveal).catch(() =>",
        "posterRequestId",
    ):
        if marker not in tour_runtime:
            raise SystemExit(f"product-tour preview performance guard is missing: {marker}")
    styles = (OUTPUT / "styles.css").read_text(encoding="utf-8")
    if not re.search(
        r"\.terminal-window\s*\{[^}]*min-height:\s*0;[^}]*aspect-ratio:\s*5\s*/\s*3;",
        styles,
        flags=re.DOTALL,
    ):
        raise SystemExit("product-tour preview frame does not preserve its 5:3 layout")

    for page_name in (
        "index.html",
        "explore.html",
        "tui.html",
        "candle.html",
        "elephant.html",
        "maples.html",
        "rubric.html",
    ):
        page = (OUTPUT / page_name).read_text(encoding="utf-8")
        stylesheet_links = re.findall(
            r'href="styles\.css\?v=([0-9a-f]{12})"',
            page,
        )
        if len(stylesheet_links) != 1:
            raise SystemExit(f"project stylesheet is not fingerprinted in {page_name}")
        if stylesheet_links[0] != digest(OUTPUT / "styles.css")[:12]:
            raise SystemExit(f"project stylesheet fingerprint is stale in {page_name}")
        if 'href="./elephant.html"' not in page or "Elephant ingestion" not in page:
            raise SystemExit(
                f"Elephant ingestion is missing from the project navigation in {page_name}"
            )
        if 'href="./rubric.html"' not in page or "Improve a rubric" not in page:
            raise SystemExit(
                f"rubric guide is missing from the project navigation in {page_name}"
            )

    home = (OUTPUT / "index.html").read_text(encoding="utf-8")
    for marker in (
        "Explore the CLI &amp; TUI",
        "Open the CLI &amp; TUI tour",
        "Follow a complete CLI &amp; MCP run",
        "Open the Candle Making tour",
        'href="./candle.html"',
        'href="assets/candle/candle-overview.gif"',
        'download="candle-overview.gif"',
        'data-ambient-terminal',
        'data-ambient-terminal-video',
        'data-ambient-terminal-toggle',
        'src="assets/candle/candle-06-run-poster.webp"',
        'data-src="assets/candle/candle-overview.webm"',
        'data-src="assets/candle/candle-overview.mp4"',
        'preload="none"',
        'Recorded terminal · silent',
        'aria-label="Play preview — recorded terminal"',
        "never calls an external model provider",
        "incurs $0 in provider charges",
        "Explore MAPLES",
        'href="./maples.html"',
        'src="assets/maples/maples-01-group.webp"',
        "There is no real learner data here",
        "the scores are fixture values",
        "viewing the tour makes no service or model calls",
        "Load and check data in Elephant",
        'href="./elephant.html"',
        'src="assets/elephant/elephant-06-dataset-poster.webp"',
        "pause for explicit approval",
        "stored file types, byte counts, and fingerprints",
        "Browse all guided tours",
        "New interactive guide",
        "Improve a rubric, one decision at a time",
        "Start the rubric improvement guide",
        'href="./rubric.html"',
        "not a recorded Rubric Maker or grading run",
    ):
        if marker not in home:
            raise SystemExit(f"homepage tour marker missing: {marker}")
    teaser_count = sum(
        "tour-teaser" in class_names.split()
        for class_names in re.findall(r'class="([^"]*)"', home)
    )
    if teaser_count != 4:
        raise SystemExit("homepage must present exactly four recorded-tour teasers")

    homepage_runtime_links = re.findall(
        r'src="homepage-terminal\.js\?v=([0-9a-f]{12})"',
        home,
    )
    if len(homepage_runtime_links) != 1:
        raise SystemExit("homepage terminal runtime is not fingerprinted")
    homepage_runtime = OUTPUT / "homepage-terminal.js"
    if homepage_runtime_links[0] != digest(homepage_runtime)[:12]:
        raise SystemExit("homepage terminal runtime fingerprint is stale")
    if homepage_runtime.stat().st_size > 6_000:
        raise SystemExit("homepage terminal runtime exceeds its 6 KB budget")
    runtime_text = homepage_runtime.read_text(encoding="utf-8")
    for runtime_marker in (
        "IntersectionObserver",
        "prefers-reduced-motion: reduce",
        "saveData",
        "visibilitychange",
        "source[data-src]",
        "pagehide",
        "userPaused",
        "Pause preview — recorded terminal",
    ):
        if runtime_marker not in runtime_text:
            raise SystemExit(
                f"homepage terminal runtime guard is missing: {runtime_marker}"
            )
    if re.search(
        r'<source\s+[^>]*\ssrc="assets/candle/candle-overview\.(?:webm|mp4)"',
        home,
    ):
        raise SystemExit("homepage terminal motion must not load before activation")
    video_match = re.search(
        r'<video\s+[^>]*data-ambient-terminal-video[^>]*>',
        home,
    )
    if not video_match:
        raise SystemExit("homepage ambient terminal video is missing")
    for attribute in (
        "autoplay",
        "muted",
        "loop",
        "playsinline",
        'tabindex="-1"',
        'aria-hidden="true"',
    ):
        if attribute not in video_match.group(0):
            raise SystemExit(
                f"homepage ambient terminal video is missing {attribute}"
            )
    toggle_match = re.search(
        r'<button\s+[^>]*data-ambient-terminal-toggle[^>]*>',
        home,
    )
    if (
        not toggle_match
        or 'aria-controls="homepage-candle-terminal"' not in toggle_match.group(0)
    ):
        raise SystemExit("homepage terminal motion lacks an accessible pause control")
    if " hidden" not in toggle_match.group(0):
        raise SystemExit("homepage terminal control must remain hidden without JavaScript")
    ambient_media_match = re.search(
        r'<div\s+class="[^"]*tour-teaser-media--ambient[^"]*"[^>]*>',
        home,
    )
    if (
        not ambient_media_match
        or "aria-hidden" in ambient_media_match.group(0)
    ):
        raise SystemExit("homepage terminal pause control must remain exposed to assistive technology")
    if home.count('id="homepage-candle-terminal"') != 1:
        raise SystemExit("homepage terminal control target must be unique")

    for page_name in ("tui.html", "candle.html", "elephant.html", "maples.html"):
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
    if 'href="./candle.html"' not in tui:
        raise SystemExit("CLI/TUI tour does not link to the Candle walkthrough")

    candle = (OUTPUT / "candle.html").read_text(encoding="utf-8")
    for marker in (
        'data-tour-id="candle-cli-mcp"',
        'id="candle-tab-inputs"',
        'id="candle-tab-run"',
        'id="candle-tab-mcp"',
        'id="candle-tab-evidence"',
        'src="product-tour.js?v=',
        "Real CLI &amp; MCP · local test fixture · $0 paid",
        "running on the same machine",
        "No note leaves the computer",
        "no external model provider is called",
        "not judgments from a live model",
        "All three calls are cache hits",
        "no requests to the local test service, no reported tokens, and no estimated cost",
        "all 22 digital fingerprints for the recorded CLI evidence are valid",
        "actual paid spend remain zero",
        "not provider charges",
        "conservative rough pre-run estimate of $0.010096",
        'id="candle-transcript"',
        'href="#candle-transcript"',
        'href="assets/candle/manifest.json"',
        'href="./explore.html"',
        'href="./tui.html"',
        'href="./maples.html"',
        'href="./index.html"',
        "Complete recorded transcript",
        "CLI and MCP: two ways to run the same workflow",
        "Explore every tour",
        "Return home",
    ):
        if marker not in candle:
            raise SystemExit(f"Candle CLI/MCP tour marker missing: {marker}")
    expected_candle_commands = [
        "oasis --format json data validate candle-data",
        "oasis --format json data scan candle-data --rubric rubric/candle-rubric.yaml --hash --summary-only --output evidence/capture/intake-manifest.json",
        "oasis --format json rubric check rubric/candle-rubric.yaml --strict",
        "oasis --format json --trace-id candle-plan auto-grade candle-data --rubric rubric/candle-rubric.yaml --provider openai-compatible --output output/capture-plan --max-files 10 --hash --no-transcript --depth shallow",
        "oasis --format json --trace-id candle-sample auto-grade candle-data --rubric rubric/candle-rubric.yaml --provider openai-compatible --output output/capture-sample --max-files 10 --hash --standalone --sample 1 --concurrency 1 --no-cache --no-transcript --depth shallow",
        "oasis --format json --trace-id candle-run auto-grade candle-data --rubric rubric/candle-rubric.yaml --provider openai-compatible --output output/capture-run --max-files 10 --hash --standalone --skip-sample --concurrency 1 --no-transcript --depth shallow",
        "oasis --format json summary output/capture-run --depth prompt",
        "oasis --format json inspect output/capture-run --verify --provenance",
        "oasis ledger --limit 10",
    ]
    candle_code_values = re.findall(r"<code>([^<]+)</code>", candle)
    for command in expected_candle_commands:
        if candle_code_values.count(command) != 1:
            raise SystemExit(f"Candle recorded command contract changed: {command}")
    full_run_code = next(
        (value for value in candle_code_values if "--trace-id candle-run" in value),
        "",
    )
    if "--no-cache" in full_run_code:
        raise SystemExit("Candle full-run command would bypass the cache used by MCP")
    candle_steps = [
        "inputs",
        "data",
        "rubric",
        "plan",
        "sample",
        "run",
        "mcp",
        "evidence",
    ]
    for step_id in candle_steps:
        no_js_anchor = re.compile(
            rf'<noscript>\s*<span\s+id="{re.escape(step_id)}"\s+'
            r'class="tour-transcript-anchor"\s+aria-hidden="true"\s*></span>\s*</noscript>'
        )
        if len(no_js_anchor.findall(candle)) != 1:
            raise SystemExit(
                f"Candle no-JS transcript anchor is missing or duplicated: {step_id}"
            )
        if candle.count(f'id="{step_id}"') != 1:
            raise SystemExit(
                f"Candle shared step hash has an ambiguous HTML target: {step_id}"
            )
        if f'href="#{step_id}"' not in candle:
            raise SystemExit(f"Candle no-JS step link is missing: {step_id}")
    candle_payload = check_tour_structure("candle.html", candle_steps)
    candle_asset_rows = candle_manifest["assets"]
    candle_posters = {
        row["scene"]: row
        for row in candle_asset_rows
        if row.get("role") == "poster"
    }
    candle_motion = {
        row["format"]: row
        for row in candle_asset_rows
        if row.get("role") == "motion"
    }
    for step in candle_payload["steps"]:
        poster = step.get("poster")
        poster_asset = candle_posters.get(step.get("id"))
        if (
            not isinstance(poster, dict)
            or not isinstance(poster_asset, dict)
            or poster.get("src") != poster_asset.get("path")
            or poster.get("srcset") != poster_asset.get("path")
            or poster.get("type") != "image/webp"
            or poster.get("width") != poster_asset.get("width")
            or poster.get("height") != poster_asset.get("height")
            or poster.get("alt") != poster_asset.get("alt")
        ):
            raise SystemExit(
                f"Candle tour poster contract is invalid: {step.get('id')}"
            )
        media = step.get("media")
        if step.get("id") == "run":
            if not isinstance(media, dict) or any(
                media.get(media_format)
                != candle_motion.get(media_format, {}).get("path")
                for media_format in ("webm", "mp4", "gif")
            ):
                raise SystemExit("Candle overview media contract is invalid")
        elif media is not None:
            raise SystemExit(
                f"unexpected Candle motion media on step: {step.get('id')}"
            )
    for forbidden_claim in (
        "live model assessment",
        "live-model output",
        "MCP replay",
        "cache replay",
        "provider bill of $0.00252",
        "uploaded into Elephant",
        "uses real student data",
    ):
        if forbidden_claim in candle:
            raise SystemExit(
                f"Candle fixture copy crosses its truth boundary: {forbidden_claim}"
            )

    elephant = (OUTPUT / "elephant.html").read_text(encoding="utf-8")
    for marker in (
        'data-tour-id="elephant-ingestion"',
        'id="elephant-tab-agent-brief"',
        'id="elephant-tab-import-run"',
        'id="elephant-tab-dataset"',
        'id="elephant-tab-file-details"',
        'src="product-tour.js?v=',
        "Recorded locally · made-up Candle records · checked and loaded with OASIS",
        "model-neutral illustration",
        "not a transcript from Claude, Codex, Grok",
        "Visitors see an offline replay",
        "contacts neither Elephant nor a model provider",
        "The approval gate shown here is a capture-harness policy",
        "not a hidden prompt built into",
        "the import runner reads a scoped write key from a private environment file",
        "the key never appears in a command or on this page",
        "use a separate read-only key",
        "That JSON is not transformed into the import CSV",
        "not make the whole command atomic or resumable",
        "does not write a durable per-row resume receipt",
        "changed inputs must go back through preview and approval",
        "Minhan Park and Licheng Yi’s public Wayfinder rubric-authoring walkthrough",
        "none of the interns’ data, prompts, or outputs were reused",
        "The interface calls this a group",
        "groups files by encounter and reports a count",
        "The current read-back did not return an original filename",
        "the tour does not claim to verify one",
        'id="elephant-transcript"',
        'href="#elephant-transcript"',
        'href="assets/elephant/manifest.json"',
        'href="./explore.html"',
        'href="./tui.html"',
        'href="./candle.html"',
        'href="./maples.html"',
        'href="./index.html"',
        "Equivalent commands for reproducing the workflow",
        "capture wrapper requested JSON output",
        "equivalent, operator-friendly command forms",
        "final screen used a small private read-back helper",
        "An equivalent direct CLI form is",
        "Complete recorded transcript",
    ):
        if marker not in elephant:
            raise SystemExit(f"Elephant ingestion tour marker missing: {marker}")
    if "--idempotency-key" in elephant:
        raise SystemExit("Elephant public capture must not recommend the unsafe import idempotency key")
    if "og_file_name" in elephant:
        raise SystemExit("Elephant public read-back must not imply that an original filename was returned")
    for command in (
        "oasis data validate candle-data",
        (
            "oasis data scan candle-data --hash --summary-only "
            "--fail-on-clarifications --output evidence/scan.json"
        ),
        "oasis data import manifest.csv --data-dir candle-data --dry-run",
        "oasis data import manifest.csv --data-dir candle-data",
        "oasis interactive",
    ):
        rendered_command = command.replace('"', "&quot;")
        if command not in elephant and rendered_command not in elephant:
            raise SystemExit(f"Elephant recorded command contract changed: {command}")
    elephant_steps = [
        "agent-brief",
        "local-checks",
        "import-preview",
        "human-approval",
        "import-run",
        "dataset",
        "encounters",
        "files",
        "file-details",
    ]
    for step_id in elephant_steps:
        no_js_anchor = re.compile(
            rf'<noscript>\s*<span\s+id="{re.escape(step_id)}"\s+'
            r'class="tour-transcript-anchor"\s+aria-hidden="true"\s*></span>\s*</noscript>'
        )
        if len(no_js_anchor.findall(elephant)) != 1:
            raise SystemExit(
                f"Elephant no-JS transcript anchor is missing or duplicated: {step_id}"
            )
        if elephant.count(f'id="{step_id}"') != 1:
            raise SystemExit(
                f"Elephant shared step hash has an ambiguous HTML target: {step_id}"
            )
        if f'href="#{step_id}"' not in elephant:
            raise SystemExit(f"Elephant no-JS step link is missing: {step_id}")
    elephant_payload = check_tour_structure("elephant.html", elephant_steps)
    elephant_assets = elephant_manifest["assets"]
    elephant_posters = {
        row["scene"]: row
        for row in elephant_assets
        if row.get("role") == "poster"
    }
    elephant_motion = {
        row["format"]: row
        for row in elephant_assets
        if row.get("role") == "motion"
    }
    for step in elephant_payload["steps"]:
        poster = step.get("poster")
        poster_asset = elephant_posters.get(step.get("id"))
        if (
            not isinstance(poster, dict)
            or not isinstance(poster_asset, dict)
            or poster.get("src") != poster_asset.get("path")
            or poster.get("srcset") != poster_asset.get("path")
            or poster.get("type") != "image/webp"
            or poster.get("width") != poster_asset.get("width")
            or poster.get("height") != poster_asset.get("height")
            or poster.get("alt") != poster_asset.get("alt")
        ):
            raise SystemExit(
                f"Elephant tour poster contract is invalid: {step.get('id')}"
            )
        media = step.get("media")
        if step.get("id") == "import-run":
            if (
                not isinstance(media, dict)
                or media.get("webm") != elephant_motion.get("webm", {}).get("path")
                or media.get("mp4") != elephant_motion.get("mp4", {}).get("path")
                or media.get("gif") is not None
            ):
                raise SystemExit("Elephant overview media contract is invalid")
        elif media is not None:
            raise SystemExit(
                f"unexpected Elephant motion media on step: {step.get('id')}"
            )
    for forbidden_claim in (
        "live agent transcript",
        "built-in approval prompt",
        "atomic import",
        "resumable import",
        "scan JSON import manifest",
        "TUI dataset object",
        "real student data",
    ):
        if forbidden_claim in elephant:
            raise SystemExit(
                f"Elephant tour copy crosses its truth boundary: {forbidden_claim}"
            )

    maples = (OUTPUT / "maples.html").read_text(encoding="utf-8")
    for marker in (
        'data-tour-id="maples"',
        'id="maples-tab-group"',
        'id="maples-tab-review"',
        'id="maples-tab-rubric-path"',
        'src="product-tour.js?v=',
        "Recorded demo · coded synthetic data · no provider calls",
        "predictable test fixture on the same machine",
        "The live MAPLES stack was not used",
        "Every displayed score, rationale, progress value, and review state was prepared for the demo",
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
        "Open the Candle CLI &amp; MCP tour",
        "Open the Elephant ingestion tour",
        "Open the MAPLES tour",
        "Available now · recorded",
        "Available now · recorded demo",
        "Watch the team demonstrate OASIS",
        "separate from the privacy-reviewed recordings on this site",
        'href="https://www.youtube.com/watch?v=tHvS2kqRc2Q"',
        'href="https://www.youtube.com/watch?v=MKwseFKuFLs"',
        'href="https://www.youtube.com/watch?v=GVAy3FPe8nI"',
        'href="https://www.youtube.com/watch?v=tZwhtWPLz1s"',
        'href="https://www.youtube.com/@JamiesonLabUTSW"',
        'href="https://ut-real-ai-project-maples.com/maples-demo-rubric-to-review/"',
        'href="https://ut-real-ai-project-maples.com/wayfinder-rubric-authoring-demo/"',
        'href="https://ut-real-ai-project-maples.com/wayfinder-grading-run-demo/"',
        'href="https://ut-real-ai-project-maples.com/sail-2026-maples-poster-walkthrough/"',
        "Available now · interactive guide",
        "Open the rubric improvement guide",
        'href="./rubric.html"',
    ):
        if marker not in explore:
            raise SystemExit(f"Explore overview marker missing: {marker}")
    if "youtube.com/embed" in explore or "youtube-nocookie.com/embed" in explore:
        raise SystemExit("Explore must link to YouTube without loading an embedded player")

    rubric = (OUTPUT / "rubric.html").read_text(encoding="utf-8")
    rubric_steps = [
        "baseline",
        "focus",
        "review",
        "compare",
        "decide",
        "trial",
        "revise",
        "ready",
    ]
    rubric_structure = RubricGuideStructureParser()
    rubric_structure.feed(rubric)
    rubric_ids = TourStructureParser()
    rubric_ids.feed(rubric)
    duplicate_rubric_ids = sorted(
        {value for value in rubric_ids.ids if rubric_ids.ids.count(value) > 1}
    )
    if duplicate_rubric_ids:
        raise SystemExit(f"duplicate HTML ids in rubric.html: {duplicate_rubric_ids}")
    if rubric_structure.guide_count != 1:
        raise SystemExit("rubric page must contain exactly one interactive guide")
    if (
        len(rubric_structure.tablists) != 1
        or rubric_structure.tablists[0].get("aria-label")
        != "Rubric improvement steps"
    ):
        raise SystemExit("rubric guide tablist label is invalid")
    if rubric_structure.media:
        raise SystemExit(
            f"rubric guide must not load images or media: {rubric_structure.media}"
        )
    if [tab.get("data-rubric-tab") for tab in rubric_structure.tabs] != rubric_steps:
        raise SystemExit("rubric guide tabs are missing or out of order")
    if [panel.get("data-rubric-panel") for panel in rubric_structure.panels] != rubric_steps:
        raise SystemExit("rubric guide panels are missing or out of order")
    if len(rubric_structure.tabs) != 8 or len(rubric_structure.panels) != 8:
        raise SystemExit("rubric guide must contain exactly eight tabs and panels")
    for index, (tab, panel) in enumerate(
        zip(rubric_structure.tabs, rubric_structure.panels, strict=True)
    ):
        expected_step = rubric_steps[index]
        if (
            tab.get("id") != f"rubric-tab-{expected_step}"
            or tab.get("role") != "tab"
            or tab.get("type") != "button"
            or tab.get("aria-controls") != expected_step
            or tab.get("aria-selected") != ("true" if index == 0 else "false")
            or tab.get("tabindex") != ("0" if index == 0 else "-1")
            or panel.get("id") != expected_step
            or panel.get("role") != "tabpanel"
            or panel.get("aria-labelledby") != f"rubric-tab-{expected_step}"
            or panel.get("tabindex") != "0"
            or "hidden" in panel
            or not panel.get("data-title")
            or not panel.get("data-summary")
        ):
            raise SystemExit(f"rubric guide ARIA contract is invalid: {expected_step}")
    if (
        [choice.get("data-rubric-choice") for choice in rubric_structure.choices]
        != ["RM-01", "RM-02", "RM-03", "RM-04"]
        or [choice.get("aria-pressed") for choice in rubric_structure.choices]
        != ["true", "true", "true", "false"]
    ):
        raise SystemExit("rubric walkthrough decision controls are invalid")

    rubric_markers = (
        "Prepared example · no Rubric Maker run",
        "outside the plugin’s documented OSCE scope",
        "Using the page does not start an agent or model, run a grader, or contact MAPLES or OASIS",
        "rubric-import",
        "osce-rubric-review",
        "alignment, safety, observability, objectivity, feasibility, and reliability",
        "osce-rubric-transform",
        "grading-dry-run",
        "evaluate-dry-run",
        "not output from a Rubric Maker review run",
        "editorial illustrations, not outputs from a Rubric Maker skill run or a recorded grading run",
        "newly authored for the bicycle example with Codex assistance",
        "Prepared source artifact",
        "1 · unsafe",
        "2 · mostly correct",
        "3 · correct",
        "contiguous <code>Score1</code>, <code>Score2</code>, and <code>Score3</code> keys",
        "RM-01 · Score1 safety boundary",
        "RM-02 · Score2 middle anchor",
        "RM-03 · Score3 passing anchor",
        "RM-04 · Technique measurement",
        "one structured suggestion for each field or score anchor being changed",
        "RM-01 through RM-04 are editorial walkthrough labels",
        "Score 1: <code>incorrect</code>",
        "Score 2: <code>mostly correct</code>",
        "Score 3: <code>correct</code>",
        "<code>Technique</code> is empty in the prepared source",
        "Score 3 when both pads contact the rim",
        "use 1 and stop when the observation shows a damaged rim",
        "use 2 when no stop condition is present",
        "use 3 only when every passing check is visible",
        "<code>unscorable: true</code>",
        "This is not a fourth rubric score anchor",
        "evidence mode, and contiguous <code>Score1</code>…<code>ScoreN</code> ordering",
        "Prepared trial",
        "3 · meets",
        "1 · stop",
        "2 · revise",
        "not an executed transform or validation result",
        "Before approval, confirm",
        "Obtain sign-off from domain experts and intended reviewers",
        "walkthrough controls only",
        "name the suggestions or rubric locations to apply",
        "prepared v2 below stays fixed to the initial RM-01, RM-02, and RM-03 decision",
        "a visible gap returns at both pads and neither pad remains against the rim",
        "do not imitate native Rubric Maker, Wayfinder, MAPLES, or SimRubrics controls",
        "Wayfinder Rubric Studio is the MAPLES web experience",
        "SimRubrics is a separate research application",
        "or a claim that MAPLES evolved from it",
        "academic-research-only license",
        "JavaScript is off, so all eight steps are shown in order",
        'href="https://ut-real-ai-project-maples.com/mt-docs/"',
        'href="https://ut-real-ai-project-maples.com/mt-docs/rubric-maker-skill/"',
        'href="https://ut-real-ai-project-maples.com/wayfinder-rubric-authoring-demo/"',
        'href="https://www.youtube.com/watch?v=MKwseFKuFLs"',
        'href="https://github.com/JamiesonLabUTSW/maples-toolkit/releases/tag/rubric-maker-skill%2Fv0.1.0"',
        'href="./explore.html"',
        'href="./maples.html"',
        'href="./index.html"',
    )
    for marker in rubric_markers:
        if marker not in rubric:
            raise SystemExit(f"rubric guide truth or navigation marker missing: {marker}")
    for forbidden in (
        "zero-shot",
        "oasis rubric check",
        "actual agent result",
        "actual model result",
        "Rubric Maker web app",
        "MAPLES evolved from SimRubrics",
        "0 · unsafe",
        "0 · stop",
        "use 0 and stop",
        "not observed",
        "validated scope",
        "no skill, agent, or model produced them",
        "name the suggestion IDs",
        "Review suggestions by ID",
        "wheel turns freely by hand",
    ):
        if forbidden in rubric:
            raise SystemExit(f"rubric guide crosses its method boundary: {forbidden}")
    if re.search(r'<script\s+[^>]*src="(?:https?:)?//', rubric):
        raise SystemExit("rubric guide must not load a third-party script")
    if re.search(r'<(?:iframe|video|audio|picture)\b', rubric):
        raise SystemExit("rubric page must not embed third-party or motion media")

    rubric_runtime_links = re.findall(
        r'src="rubric-guide\.js\?v=([0-9a-f]{12})"',
        rubric,
    )
    rubric_runtime = OUTPUT / "rubric-guide.js"
    if len(rubric_runtime_links) != 1:
        raise SystemExit("rubric guide runtime is not fingerprinted")
    if rubric_runtime_links[0] != digest(rubric_runtime)[:12]:
        raise SystemExit("rubric guide runtime fingerprint is stale")
    if rubric_runtime.stat().st_size > 6_000:
        raise SystemExit("rubric guide runtime exceeds its 6 KB budget")
    rubric_runtime_text = rubric_runtime.read_text(encoding="utf-8")
    for marker in (
        'guide.setAttribute("data-rubric-enhanced", "")',
        'panel.setAttribute("aria-hidden", String(!active))',
        'tab.setAttribute("aria-selected", String(active))',
        'button.setAttribute("aria-pressed", String(!pressed))',
        'event.key === "ArrowRight"',
        'event.key === "Home"',
        'event.key === "End"',
        "window.history.pushState",
        'window.addEventListener("hashchange"',
    ):
        if marker not in rubric_runtime_text:
            raise SystemExit(f"rubric guide interaction guard is missing: {marker}")
    for network_api in ("fetch(", "XMLHttpRequest", "WebSocket", "sendBeacon"):
        if network_api in rubric_runtime_text:
            raise SystemExit(f"rubric guide runtime must remain offline: {network_api}")
    for invalid_tab_key in ('event.key === "ArrowDown"', 'event.key === "ArrowUp"'):
        if invalid_tab_key in rubric_runtime_text:
            raise SystemExit(
                f"horizontal rubric tabs must preserve page scrolling: {invalid_tab_key}"
            )

    for style_contract in (
        r"\.rubric-step-tabs,\s*\.rubric-guide-progress,\s*\.rubric-guide-controls\s*\{[^}]*display:\s*none;",
        r"\[data-rubric-guide\]\[data-rubric-enhanced\]\s+\.rubric-step-tabs\s*\{[^}]*display:\s*flex;",
        r"\.rubric-step-tabs button\s*\{[^}]*min-height:\s*44px;",
        r"\.rubric-step-tabs button:focus-visible,[^{]*\{[^}]*outline:\s*3px solid #79cfff;",
        r"\.rubric-decision-controls\s*\{[^}]*display:\s*none;",
        r"\[data-rubric-guide\]\[data-rubric-enhanced\]\s+\.rubric-decision-controls\s*\{[^}]*display:\s*grid;",
        r"\.rubric-step-layout\s*\{[^}]*grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\);",
        r"\.rubric-step-panel:focus-visible\s*\{[^}]*box-shadow:\s*inset 0 0 0 3px #79cfff;",
        r"\.rubric-deep-link\s*\{[^}]*min-height:\s*44px;",
        r"\.rubric-guide \.eyebrow,[^{]*\{[^}]*color:\s*#e0876a;",
        r"\.rubric-step-panel code\s*\{[^}]*white-space:\s*normal;[^}]*word-break:\s*break-all;",
    ):
        if not re.search(style_contract, styles, flags=re.DOTALL):
            raise SystemExit(f"rubric guide fallback or accessibility style is missing: {style_contract}")

    styles = (OUTPUT / "styles.css").read_text(encoding="utf-8")
    for motion_style_contract in (
        r"\.ambient-terminal-toggle\s*\{[^}]*min-width:\s*44px;[^}]*min-height:\s*44px;",
        r"\.ambient-terminal-toggle:focus-visible\s*\{[^}]*outline:\s*3px solid #79cfff;",
        r"\.ambient-terminal:not\(\.motion-enabled\) video\s*\{[^}]*display:\s*none;",
        r"\.ambient-terminal img\s*\{[^}]*opacity:\s*1 !important;",
    ):
        if not re.search(motion_style_contract, styles, flags=re.DOTALL):
            raise SystemExit(
                f"homepage terminal accessibility rule is missing: {motion_style_contract}"
            )
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
    if not re.search(
        r"\.tour-transcript-anchor\s*\{[^}]*display:\s*block;[^}]*scroll-margin-top:\s*5rem;",
        styles,
        flags=re.DOTALL,
    ):
        raise SystemExit("no-JS transcript anchors lack stable sticky-header spacing")

    teaser_rules = re.findall(r"\.tour-teaser-media img\s*\{([^}]*)\}", styles)
    ratio_rule = next(
        (rule for rule in teaser_rules if "aspect-ratio" in rule),
        None,
    )
    if not ratio_rule or not re.search(r"\bheight\s*:\s*auto\s*;", ratio_rule):
        raise SystemExit("homepage tour teasers do not preserve their intrinsic aspect ratio")
    if not re.search(r"\baspect-ratio\s*:\s*5\s*/\s*3\s*;", ratio_rule):
        raise SystemExit("homepage tour teasers are missing their 5:3 media contract")

    publication = json.loads((OUTPUT / "publication.json").read_text(encoding="utf-8"))
    demo = publication.get("software_demonstrations", {})
    if not (
        demo.get("recorded")
        and demo.get("live_service") is False
        and demo.get("path") == "explore.html"
        and demo.get("tour_count") == 4
        and demo.get("data_classification") == "declared per tour"
    ):
        raise SystemExit("publication demonstration scope is not explicit")
    if len(publication.get("demo_media", [])) != (
        27 + len(candle_asset_rows) + len(elephant_assets)
    ):
        raise SystemExit("publication media inventory is incomplete")
    capture_manifests = publication.get("capture_manifests", [])
    if (
        len(capture_manifests) != 4
        or {item.get("tour_id") for item in capture_manifests}
        != {"cli-tui", "candle-cli-mcp", "elephant-ingestion", "maples"}
    ):
        raise SystemExit("publication capture-manifest inventory is incomplete")
    if publication.get("tour_overview") != "explore.html":
        raise SystemExit("publication tour overview is missing")
    guide_rows = publication.get("interactive_guides", [])
    if not isinstance(guide_rows, list) or len(guide_rows) != 1:
        raise SystemExit("publication interactive-guide inventory is invalid")
    rubric_guide = guide_rows[0]
    if (
        set(rubric_guide)
        != {
            "id",
            "title",
            "path",
            "status",
            "recorded",
            "live_service",
            "visitor_network_calls",
            "rubric_maker_skill_run",
            "recorded_grading_run",
            "editorial_assistance",
            "data_classification",
            "real_person_data",
            "example_domain",
            "method",
            "documented_scope",
            "example_within_documented_scope",
            "step_count",
        }
        or rubric_guide.get("id") != "rubric-improvement"
        or rubric_guide.get("title") != "Improve a rubric, one decision at a time"
        or rubric_guide.get("path") != "rubric.html"
        or rubric_guide.get("status") != "interactive"
        or rubric_guide.get("recorded") is not False
        or rubric_guide.get("live_service") is not False
        or rubric_guide.get("visitor_network_calls") is not False
        or rubric_guide.get("rubric_maker_skill_run") is not False
        or rubric_guide.get("recorded_grading_run") is not False
        or rubric_guide.get("editorial_assistance") != "Codex"
        or rubric_guide.get("data_classification") != "newly-authored-synthetic"
        or rubric_guide.get("real_person_data") is not False
        or rubric_guide.get("example_domain") != "bicycle maintenance"
        or rubric_guide.get("method") != "Rubric Maker v0.1.0"
        or rubric_guide.get("documented_scope") != "OSCE-focused rubric workflows"
        or rubric_guide.get("example_within_documented_scope") is not False
        or rubric_guide.get("step_count") != 8
    ):
        raise SystemExit("publication rubric-guide truth boundary is invalid")
    tour_rows = publication.get("tours", [])
    tours = {item.get("id"): item for item in tour_rows}
    if len(tours) != len(tour_rows):
        raise SystemExit("publication tour catalog contains duplicate ids")
    if set(tours) != {
        "cli-tui",
        "candle-cli-mcp",
        "elephant-ingestion",
        "maples",
    }:
        raise SystemExit("publication tour catalog is incomplete")
    if not tours["cli-tui"].get("recorded") or tours["cli-tui"].get("path") != "tui.html":
        raise SystemExit("publication CLI/TUI tour record is invalid")
    candle_tour = tours["candle-cli-mcp"]
    candle_scenario = candle_manifest["scenario"]
    candle_application = candle_manifest["application"]
    candle_boundary = candle_manifest["execution_boundary"]
    sample_boundary = candle_boundary["sample"]
    full_boundary = candle_boundary["cli_full_run"]
    mcp_boundary = candle_boundary["mcp_cache_backed_run"]
    campaign_boundary = candle_boundary["campaign_total"]
    cli_integrity = candle_boundary["cli_integrity"]
    mcp_integrity = candle_boundary["mcp_integrity"]
    if (
        candle_tour.get("recorded") is not True
        or candle_tour.get("status") != "recorded"
        or candle_tour.get("path") != "candle.html"
        or candle_tour.get("live_service") is not False
        or candle_tour.get("synthetic_or_sanitized") is not True
        or candle_tour.get("data_classification") != "synthetic-coded"
        or candle_tour.get("real_person_data") is not False
        or candle_tour.get("visitor_network_calls") is not False
        or candle_tour.get("grading_pipeline_invoked") is not True
        or candle_tour.get("external_provider_calls")
        != candle_boundary.get("capture_external_provider_calls")
        or candle_tour.get("sample_loopback_requests")
        != sample_boundary.get("loopback_requests")
        or candle_tour.get("full_run_loopback_requests")
        != full_boundary.get("loopback_requests")
        or candle_tour.get("capture_loopback_requests_total")
        != campaign_boundary.get("loopback_requests")
        or candle_tour.get("sample_fixture_scores")
        != sample_boundary.get("item_scores")
        or candle_tour.get("full_run_fixture_scores")
        != full_boundary.get("item_scores")
        or candle_tour.get("capture_fixture_scores_total")
        != campaign_boundary.get("item_scores")
        or candle_tour.get("sample_fixture_tokens")
        != sample_boundary.get("fixture_reported_tokens")
        or candle_tour.get("full_run_fixture_tokens")
        != full_boundary.get("fixture_reported_tokens")
        or candle_tour.get("capture_fixture_tokens_total")
        != campaign_boundary.get("fixture_reported_tokens")
        or candle_tour.get("plan_rough_estimated_cost_usd")
        != candle_boundary.get("plan_rough_estimated_cost_usd")
        or candle_tour.get("sample_estimated_cost_usd")
        != sample_boundary.get("oasis_estimated_cost_usd")
        or candle_tour.get("full_run_estimated_cost_usd")
        != full_boundary.get("oasis_estimated_cost_usd")
        or candle_tour.get("capture_estimated_cost_usd")
        != campaign_boundary.get("oasis_estimated_cost_usd")
        or candle_tour.get("paid_spend_usd") != candle_boundary.get("paid_usd")
        or candle_tour.get("mcp_cache_hits") != mcp_boundary.get("cache_hits")
        or candle_tour.get("mcp_new_loopback_requests")
        != mcp_boundary.get("new_loopback_requests")
        or candle_tour.get("mcp_new_fixture_tokens")
        != mcp_boundary.get("new_fixture_reported_tokens")
        or candle_tour.get("mcp_incremental_estimated_cost_usd")
        != mcp_boundary.get("new_estimated_cost_usd")
        or candle_tour.get("evidence_hashes_verified")
        != cli_integrity.get("verified")
        or candle_tour.get("evidence_hashes_total") != cli_integrity.get("total")
        or candle_tour.get("mcp_evidence_hashes_verified")
        != mcp_integrity.get("verified")
        or candle_tour.get("mcp_evidence_hashes_total")
        != mcp_integrity.get("total")
        or candle_tour.get("capture_state") != "verified-loopback-fixture"
        or candle_tour.get("scenario_id") != candle_scenario.get("id")
        or candle_tour.get("source_head_sha")
        != candle_application.get("source_revision")
        or len(candle_tour.get("media_assets", [])) != len(candle_asset_rows)
    ):
        raise SystemExit("publication Candle CLI/MCP recorded-tour contract is invalid")
    publication_candle_media = {
        row.get("path"): row for row in candle_tour.get("media_assets", [])
    }
    for row in candle_asset_rows:
        published = publication_candle_media.get(row["path"])
        if (
            not isinstance(published, dict)
            or published.get("bytes") != row.get("bytes")
            or published.get("sha256") != row.get("sha256")
        ):
            raise SystemExit(
                f"publication Candle media mismatch: {row.get('path')}"
            )
    elephant_tour = tours["elephant-ingestion"]
    elephant_scenario = elephant_manifest["scenario"]
    elephant_application = elephant_manifest["application"]
    elephant_execution = elephant_manifest["execution_boundary"]
    elephant_agent = elephant_execution["agent_exchange"]
    elephant_import = elephant_execution["import"]
    if (
        elephant_tour.get("recorded") is not True
        or elephant_tour.get("status") != "recorded"
        or elephant_tour.get("path") != "elephant.html"
        or elephant_tour.get("live_service") is not False
        or elephant_tour.get("synthetic_or_sanitized") is not True
        or elephant_tour.get("data_classification") != "synthetic-coded"
        or elephant_tour.get("real_person_data") is not False
        or elephant_tour.get("capture_elephant_service") != "local-loopback"
        or elephant_tour.get("visitor_network_calls") is not False
        or elephant_tour.get("external_model_provider_calls")
        != elephant_agent.get("external_model_provider_calls")
        or elephant_tour.get("dry_run_api_calls")
        != elephant_import.get("dry_run_api_calls")
        or elephant_tour.get("agent_exchange_live")
        != elephant_agent.get("live")
        or elephant_tour.get("agent_exchange_illustrated")
        != elephant_agent.get("illustrated")
        or elephant_tour.get("approval_gate") != "capture-harness"
        or elephant_tour.get("import_atomic") != elephant_import.get("atomic")
        or elephant_tour.get("import_resumable")
        != elephant_import.get("resumable")
        or elephant_tour.get("records_imported")
        != elephant_import.get("records_expected")
        or elephant_tour.get("files_imported")
        != elephant_import.get("files_expected")
        or elephant_tour.get("failed_rows") != elephant_import.get("rows_failed")
        or elephant_tour.get("capture_state") != "verified-local-elephant"
        or elephant_tour.get("scenario_id") != elephant_scenario.get("id")
        or elephant_tour.get("source_head_sha")
        != elephant_application.get("source_revision")
        or len(elephant_tour.get("media_assets", [])) != len(elephant_assets)
    ):
        raise SystemExit("publication Elephant recorded-tour contract is invalid")
    publication_elephant_media = {
        row.get("path"): row for row in elephant_tour.get("media_assets", [])
    }
    for row in elephant_assets:
        published = publication_elephant_media.get(row["path"])
        if (
            not isinstance(published, dict)
            or published.get("bytes") != row.get("bytes")
            or published.get("sha256") != row.get("sha256")
        ):
            raise SystemExit(
                f"publication Elephant media mismatch: {row.get('path')}"
            )
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
    required_pages = (
        "index.html",
        "explore.html",
        "tui.html",
        "candle.html",
        "elephant.html",
        "maples.html",
        "rubric.html",
    )
    missing_pages = [name for name in required_pages if not (OUTPUT / name).is_file()]
    if missing_pages:
        raise SystemExit(f"rendered site is incomplete; missing={missing_pages}")
    check_references()
    check_media_manifest()
    check_maples_media_manifest()
    candle_manifest = check_candle_media_manifest()
    elephant_manifest = check_elephant_media_manifest()
    check_checksums()
    check_contract(candle_manifest, elephant_manifest)
    print("OASIS project site checks: PASS")


if __name__ == "__main__":
    main()
