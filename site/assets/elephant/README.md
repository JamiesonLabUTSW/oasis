# Elephant ingestion tour media contract

This directory is reserved for a verified local recording of the
agent-assisted Elephant ingestion walkthrough. Do not add stand-in images,
placeholder hashes, or media copied from another tour.

The finished `manifest.json` must use schema
`oasis.elephant-ingestion-site-media.v1`. The site validator enforces its exact
top-level sections, synthetic scenario, local-only execution boundary, privacy
review, content-review truth markers, file order, dimensions, byte budgets, and
asset hashes.

The manifest also seals the inputs and private capture evidence without
publishing either one. Its `fixture` section records the CSV byte count and
SHA-256, the exact nine columns, the three relative note paths with byte counts
and SHA-256 values, and a canonical file-set digest. Its `evidence` section
records only sanitized evidence filenames, byte counts, SHA-256 values, and
observed counts for validation, scan, dry run, import, and read-back. Those
evidence files remain in the private capture archive; raw logs and local paths
are never copied into this public directory.

Expected posters, in order:

1. `elephant-01-agent-brief-poster.webp`
2. `elephant-02-local-checks-poster.webp`
3. `elephant-03-import-preview-poster.webp`
4. `elephant-04-human-approval-poster.webp`
5. `elephant-05-import-run-poster.webp`
6. `elephant-06-dataset-poster.webp`
7. `elephant-07-encounters-poster.webp`
8. `elephant-08-files-poster.webp`
9. `elephant-09-file-details-poster.webp`

The two motion assets are `elephant-overview.webm` and
`elephant-overview.mp4`. Posters are 1200×720 static, metadata-free WebP files.
Motion is 960×576, silent, and encoded as VP9 WebM plus H.264 MP4. An animated
GIF is intentionally not part of the page payload.

The public capture may contain only the three synthetic DEMO codes and their
reserved `example.com` documentation addresses. It must not contain a key, token, private
path, host name, pre-signed URL, real-person information, or model chain of
thought. Every poster and sampled motion frame must pass OCR and manual review
before `manifest.json` is written.
