# OASIS

**Open Assessment and Scoring Infrastructure Stack**

OASIS is a systems platform for rubric-based assessment of video, audio, and
text with large language models. It works with hosted APIs or
institution-controlled open-weight models through Ollama and OpenAI-compatible
endpoints such as vLLM. Modality-aware execution, provenance capture, and human
review keep scores inspectable from rubric definition through adjudication.

## Hosted or local inference

Model choice is an explicit part of an OASIS run rather than a platform
lock-in. Recent internal engineering runs have exercised local vLLM endpoints
with Gemma and Qwen model families across text grading, transcript-first audio,
frame-presented video, and selected native-audio research paths. These runs
demonstrate an operating capability, not a universal model-performance
benchmark; modality support and output quality depend on the selected model,
runtime, and media presentation.

A workflow is fully local only when every active stage—including
transcription, primary grading, and any schema-conversion or post-processing
model—runs on institution-controlled infrastructure. A local primary paired
with a hosted converter is a hybrid workflow.

## Technical report

- [Read the technical report online](https://jamiesonlabutsw.github.io/oasis/paper/paper.html)
- [Download the technical report as PDF](https://jamiesonlabutsw.github.io/oasis/paper/OASIS_technical_report.pdf)

## Related projects and demonstrations

- [Explore the UT-REAL multi-site MAPLES project](https://ut-real-ai-project-maples.com/)
- [Watch Ameer Hamza Shakur demonstrate the MAPLES grading and faculty-review workflow](https://www.youtube.com/watch?v=tHvS2kqRc2Q)
- [Watch Minhan Park and Licheng Yi demonstrate Wayfinder rubric authoring in MAPLES](https://www.youtube.com/watch?v=MKwseFKuFLs)

## Publication scope

Project information and this technical report are available through
[https://github.com/JamiesonLabUTSW/oasis](https://github.com/JamiesonLabUTSW/oasis)
and
[https://jamiesonlabutsw.github.io/oasis/](https://jamiesonlabutsw.github.io/oasis/).
Application and component source code, binaries, installation materials, sample
data, and a tagged software release are not included in the current public
publication.

The public repository and site contain no application source or installable
package.
