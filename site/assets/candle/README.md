# Candle CLI and MCP tour media

This directory contains the privacy-reviewed media and machine-readable
capture manifest for the standalone Candle Making walkthrough.

The page contract expects eight 1200×720 static WebP posters:

1. `candle-01-inputs-poster.webp`
2. `candle-02-data-poster.webp`
3. `candle-03-rubric-poster.webp`
4. `candle-04-plan-poster.webp`
5. `candle-05-sample-poster.webp`
6. `candle-06-run-poster.webp`
7. `candle-07-mcp-poster.webp`
8. `candle-08-evidence-poster.webp`

The opt-in overview uses `candle-overview.webm`, `candle-overview.mp4`, and
`candle-overview.gif`. The `manifest.json` schema is
`oasis.candle-cli-mcp-site-media.v1`; it records exact hashes, dimensions,
duration, privacy findings, source and binary identity, and the CLI/MCP
execution evidence. Media must not be added without the matching sealed
manifest values.
