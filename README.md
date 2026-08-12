# OASIS

**Open Assessment and Scoring Infrastructure Stack**

OASIS grades video, audio, and text against evaluator-defined rubrics, using
hosted or self-hosted large language models. Modality-aware execution,
provenance capture, and human review keep scores inspectable from rubric
definition through adjudication.

## Project site

The source for the project website lives in [`site/`](site/). It includes a
lightweight, recorded CLI and TUI tour and the prebuilt technical-report
publication artifacts. The tour uses sanitized fixtures and does not call a
model or a live clinical service.

Build the site with Quarto 1.6.42:

```bash
./scripts/build-site.sh
```

The generated site is written to `site/_site/`. Changes merged to `main` are
rendered and published to the existing `gh-pages` branch by GitHub Actions.

## Technical report

- [Read the technical report online](https://jamiesonlabutsw.github.io/oasis/paper/paper.html)
- [Download the technical report (PDF)](https://jamiesonlabutsw.github.io/oasis/paper/OASIS_technical_report.pdf)

## Related projects and demonstrations

MAPLES is the platform's grading and review application; Wayfinder is the
assistant embedded in it.

- [Explore UT-REAL, a multi-site MAPLES project](https://ut-real-ai-project-maples.com/)
- [Watch Ameer Hamza Shakur demonstrate the MAPLES grading and faculty-review workflow](https://www.youtube.com/watch?v=tHvS2kqRc2Q)
- [Watch Minhan Park and Licheng Yi demonstrate rubric authoring with Wayfinder in MAPLES](https://www.youtube.com/watch?v=MKwseFKuFLs)

## Publication scope

Project information, sanitized recorded software demonstrations, and this
technical report are available at
[https://github.com/JamiesonLabUTSW/oasis](https://github.com/JamiesonLabUTSW/oasis)
and
[https://jamiesonlabutsw.github.io/oasis/](https://jamiesonlabutsw.github.io/oasis/).
Application and component source code, binaries, installation materials, sample
data, and tagged software releases are not part of this publication.
