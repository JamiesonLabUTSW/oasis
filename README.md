# OASIS

**Open Assessment and Scoring Infrastructure Stack**

OASIS grades video, audio, and text against evaluator-defined rubrics, using
hosted or self-hosted large language models. Modality-aware execution,
provenance capture, and human review keep scores inspectable from rubric
definition through adjudication.

## Project site

The source for the project website lives in [`site/`](site/). It includes a
guided-tour overview, lightweight recorded CLI/TUI and MAPLES lifecycle
tours, a full standalone Candle CLI/MCP walkthrough, and the prebuilt
technical-report publication artifacts. Each tour declares whether its fixture
is synthetic or sanitized, along with its provider-call and live-service
boundary.

Build the site with Quarto 1.6.42:

```bash
./scripts/build-site.sh
```

The generated site is written to `site/_site/`. Changes merged to `main` are
rendered, validated, and deployed to GitHub Pages as an immutable Actions
artifact.

## Technical report

- [Read the technical report online](https://jamiesonlabutsw.github.io/oasis/paper/paper.html)
- [Download the technical report (PDF)](https://jamiesonlabutsw.github.io/oasis/paper/OASIS_technical_report.pdf)

## Related projects and demonstrations

MAPLES is the platform's grading and review application. Wayfinder Rubric
Studio is its authoring assistant; Wayfinder Operator is the CLI/TUI sibling.
They share an ecosystem name but are not the same interface.

- [Explore UT-REAL, a multi-site MAPLES project](https://ut-real-ai-project-maples.com/)
- [Watch Ameer Hamza Shakur demonstrate the MAPLES grading and faculty-review workflow](https://www.youtube.com/watch?v=tHvS2kqRc2Q)
- [Watch Minhan Park and Licheng Yi demonstrate rubric authoring with Wayfinder in MAPLES](https://www.youtube.com/watch?v=MKwseFKuFLs)

The recorded MAPLES tour uses a new Perfume-to-Candle reconstruction inspired
by Minhan Park and Licheng Yi's public walkthrough. Its rubric wording, notes,
scores, rationales, and coded records were newly authored for the website; it
does not reproduce their original prompts, outputs, data, or runtime.

The recorded Candle walkthrough uses three newly authored coded notes with the
real OASIS CLI and MCP server. Its assessment requests are served by a
deterministic OpenAI-compatible endpoint bound to loopback, so the recording
exercises OASIS planning, provider-adapter, parsing, cache, and evidence paths
without sending data to an external provider. Displayed scores and token counts
are fixture values. The dry-run amount is a conservative rough planning
estimate, while the post-execution amounts are OASIS usage-derived estimates;
none is a bill, and actual paid spend is $0.

## Publication scope

Project information, guided product tours, recorded software
demonstrations, and this technical report are available at
[https://github.com/JamiesonLabUTSW/oasis](https://github.com/JamiesonLabUTSW/oasis)
and
[https://jamiesonlabutsw.github.io/oasis/](https://jamiesonlabutsw.github.io/oasis/).
Application and component source code, binaries, installation materials, sample
data, and tagged software releases are not part of this publication.
