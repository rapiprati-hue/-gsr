# oriori_gsr

A local-first cognitive-science booth workspace. Korean operator dashboard, participant tablet flow, fixed-template receipt, raw data/events, PostgreSQL demo workspace, and a downloadable self-contained Python app.

## User quick start
- Open the app and choose **시작 가이드**.
- Download **oriori_gsr.zip** from the sidebar or guide.
- Extract the archive, install Python 3.11+, and run `start_windows.bat` (Windows) or `bash start_mac.sh` (macOS).
- Run one demo end-to-end before attaching hardware.
- Detailed Korean setup: [Python README](python/oriori_gsr/README.md).

The public Next.js preview is **synthetic demo only**. Actual Pico/ESC-POS hardware is handled by the local Python package. Live hardware and OS drivers require on-site verification.

## Web application
Next.js App Router, React, PostgreSQL, Drizzle ORM. Routes:
- `/`: operator workspace with 7 working sections.
- `/tablet?session=<uuid>`: consent, 10-question exploration, timed course tasks, result.
- `/result/<uuid>`: receipt, 58/80mm print layout and PDF fallback.
- `/api/workspace`, `/api/sessions`, `/api/sensor`, `/api/settings`, `/api/export`.
- `/api/health`: database health check.
- `/downloads/oriori_gsr.zip` and `/downloads/README.md`.

`DATABASE_URL` is server-side. `OPENAI_API_KEY` and optional `OPENAI_MODEL` enable consent-gated optional explanations. Never store credentials in the client. Web data access is intentionally open for a synthetic demo; add real authentication, authorization, retention automation and an approved consent process before any public real-person deployment.

## Development
Dependencies are installed via npm. Apply the schema using `npx drizzle-kit push` after the platform database is bootstrapped. The schema is in `src/db/schema.ts`, database access in `src/db/index.ts`.

Validation: `npx next typegen`, `npm exec tsc -- --noEmit --pretty false`, `npm run build`, then the platform-managed build/start healthcheck.

`node scripts/package.mjs` bundles the same React frontend for the Python server, copies local licensed fonts, and creates the ZIP with a SHA-256 manifest. Source updates require regenerating the archive. The ZIP excludes data, actual .env files, virtual environments, logs and Python caches.

`node scripts/smoke.mjs` exercises a running app's dashboard, search, consent, 10 answers, five timed responses, report, exports, settings, ZIP and mobile layout. Set TEST_BASE_URL to test the standalone Python app instead. The script deletes its test session.

Python tests: with the portable requirements installed, run `python -m unittest test_engine -v` in `python/oriori_gsr`. Tests use isolated temporary data. Use `analyze.py` for descriptive raw-first QC summaries.

## Scientific and ethical boundaries
The original 10-item survey is **exploratory and not psychometrically validated**. Four-letter output is a non-official, heuristic reference, not a validated Big5-to-MBTI conversion. Scores are response-range transformations, not population percentiles. Uncalibrated ADC does not measure emotion categories, lying, vagal function or personality. Speech is optional and is not standard TSST. Environment is recorded, not used for unvalidated correction. No original audio or names are collected. Research use is disabled by default; school approval and applicable guardian/participant and institutional ethics requirements remain necessary.

See [protocol](python/oriori_gsr/PROTOCOL.md) and [data dictionary](python/oriori_gsr/DATA_DICTIONARY.md). Portfolio strength comes from transparent limitations and reproducibility, not overstated psychological conclusions.
