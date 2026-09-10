# Lead Machine / Summit

Lead Machine is a local business-discovery, lead-review, and website-monitoring application. The **Summit** interface runs in a browser or a native desktop window and brings together discovery scans, a lead database, website audits, AI-assisted drafts, and outreach exports.

Search presets cover **Colorado, California, Southern California, and Orange County / San Diego**. The California preset includes both southern and northern/central cities. The existing `colorado-lead-machine` directory and default output-folder name are retained for compatibility.

**Security:** This is a local, single-user application. Keep the server on loopback,
keep real credentials and client data out of Git, and run the full-history release
check before publishing. See [SECURITY.md](SECURITY.md).

## Features

- **Discovery:** Seed candidates with Overture, Google, or Hybrid mode; select cities, business categories, scan profiles, and opportunity focus; deduplicate and filter candidates.
- **Lead enrichment:** Resolve business websites, find contact information, check business and license records where supported, detect technology stacks, and assess website opportunities. Record checks include Colorado records and California contractor-license checks.
- **Lead review:** Browse leads, review audit evidence, track activity, rerun checks, and export scored results to Excel.
- **AI and outreach:** Generate lead-specific drafts, prepare outreach messages, and export drafts for Outlook with export history.
- **Website Monitor:** Track owned or observed sites with technical SEO checks, PageSpeed measurements, keyword rankings, competitor results, issue history, and changes between scans.

Website Monitor uses separate `website_monitor_*` tables in the configured SQLite database. Adding a monitored site does not add it to discovery or outreach. The former Website Studio and manual-website pages redirect to Website Monitor; former Studio editor links redirect to the corresponding lead. Website-generation, scraping, and validation modules remain in the repository and API.

## Install

Use Python **3.11 or newer**. Run the following commands from the repository root, the folder containing this README.

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r BrowserApp/colorado-lead-machine/requirements.txt -r BrowserApp/summit-web/requirements.txt
```

If your Python installation exposes `py` instead of `python`, use `py -3 -m venv .venv` for the first command. After activation, use `python` as shown.

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r BrowserApp/colorado-lead-machine/requirements.txt -r BrowserApp/summit-web/requirements.txt
```

The [pipeline requirements](BrowserApp/colorado-lead-machine/requirements.txt) provide discovery, enrichment, and Excel support. The [Summit requirements](BrowserApp/summit-web/requirements.txt) add FastAPI, Uvicorn, templates, desktop support, and scraping dependencies. Install both for the application.

### Optional feature dependencies

AI features require the SDK for the provider selected in Settings. These SDKs are not included in the requirements files; install the one you use:

```bash
python -m pip install openai
# Or, for Anthropic:
python -m pip install anthropic
```

For Playwright-based browser fallback, scraping, or preview checks, install Chromium in the same Python environment:

```bash
python -m playwright install chromium
```

The retained website-validation tooling also uses Node.js dependencies from [the validator package](BrowserApp/lead-vault/validator/package.json). Use Node.js 22.19 or newer within version 22, or version 24 or newer. If using those checks, install the reviewed lockfile from the repository root:

```powershell
npm.cmd --prefix BrowserApp/lead-vault/validator ci --ignore-scripts
```

On macOS/Linux, use `npm` in place of `npm.cmd`. The main browser application does not require an npm build.

## Run Summit

With the virtual environment active, run either launcher from the repository root.

**Browser application:**

```bash
python BrowserApp/summit-web/run.py
```

Open [Summit locally](http://127.0.0.1:8000). The web launcher binds to `127.0.0.1`; set the optional `PORT` environment variable to change its default port of `8000`. The API schema is available at [the local OpenAPI schema](http://127.0.0.1:8000/openapi.json). CDN-backed interactive API docs are disabled so third-party scripts cannot run with access to local settings. The retained source editor uses its built-in textarea fallback for the same reason.

**Desktop application:**

```bash
python BrowserApp/desktop_launcher.py
```

The desktop launcher starts the same backend and opens a pywebview window. It prefers `PORT` or `8000`, selects a free port if needed, and exits when the window closes. The desktop window requires a working native webview runtime; the browser launcher is also available.

### Main pages

| Page | Route | Purpose |
| --- | --- | --- |
| Dashboard | `/` | Review the current lead pipeline. |
| Discovery | `/discovery` | Configure and run business-discovery scans. |
| Leads | `/leads` | Review leads, audit evidence, drafts, and activity. |
| Website Monitor | `/website-monitor` | Track sites, SEO issues, rankings, and scan history. |
| Settings | `/settings` | Configure providers, output paths, and AI settings. |

## Configuration and storage

Start with **Settings** in the app. Provider credentials and options are saved locally in:

- `BrowserApp/colorado-lead-machine/settings.json`: discovery providers, search options, enrichment settings, and output folder.
- `BrowserApp/lead-vault/lead_vault_settings.json`: database path, AI provider/model, and agency settings.

These files are ignored by Git and may contain API keys. Keep credentials in local configuration and out of committed examples. Settings loading and defaults are defined in [app/config.py](BrowserApp/summit-web/app/config.py).

| Capability | Configuration |
| --- | --- |
| Google or Hybrid discovery | Google Maps API key. |
| Overture or Hybrid discovery | DuckDB, included in the pipeline requirements. Hybrid seeds from Overture and uses Google for verification. |
| Email and additional business enrichment | Optional Hunter, Yelp, DataForSEO, and California SOS credentials, depending on the checks used. |
| PageSpeed measurements | PageSpeed API key for Website Monitor; lead-discovery checks have an enable switch and run cap and can fall back to the Google Maps key. |
| Website Monitor keyword rankings and competitors | DataForSEO login and password, plus keywords and search settings for each tracked site. |
| Additional technology detection | Optional BuiltWith key and enabled checks. |
| AI drafts | Selected OpenAI or Anthropic provider, its SDK, API key, and model. |

Website Monitor can perform technical page checks without PageSpeed or DataForSEO credentials; those provider measurements are skipped when their credentials are missing. Add a site and keywords on the monitor page, run a scan, and review the results and history there.

By default, the SQLite database is `~/Documents/Colorado Lead Machine/lead_machine.db`. Discovery writes reports, caches, and Excel output under its configured output folder. Summit resolves its database from the Lead Vault database setting, with an output-folder fallback when that setting is blank. When changing storage locations, keep the discovery output folder and the Summit database path aligned so the app reads the intended discovery database.

## Use the pipeline from Python

For scripts that only need discovery and Excel output, install the pipeline requirements and run from `BrowserApp/colorado-lead-machine` so its modules are importable. This example reads a key from the script's environment; the app launchers use the Settings files described above.

```python
import os
from pathlib import Path

from lead_machine import LeadMachine, LeadMachineConfig

config = LeadMachineConfig(
    google_maps_api_key=os.environ["GOOGLE_MAPS_API_KEY"],
    save_path=Path.home() / "Documents" / "Colorado Lead Machine",
    search_areas=["Denver, CO", "Irvine, CA"],
    seed_mode="Hybrid",
)

machine = LeadMachine(config, logger=print)
output_file = machine.run()
print(output_file)
```

## Repository layout

| Path | Responsibility |
| --- | --- |
| [BrowserApp/summit-web/](BrowserApp/summit-web/) | FastAPI application, page templates, static assets, API routes, and web launcher. |
| [BrowserApp/desktop_launcher.py](BrowserApp/desktop_launcher.py) | Native desktop wrapper for the Summit backend. |
| [BrowserApp/colorado-lead-machine/](BrowserApp/colorado-lead-machine/) | Discovery pipeline, search presets, presence checks, contact and record enrichment, scoring, storage, and Excel reporting. |
| [BrowserApp/lead-vault/](BrowserApp/lead-vault/) | Lead persistence, AI and outreach tools, plus website generation, scraping, and validation modules. |
| [BrowserApp/shared_schema.py](BrowserApp/shared_schema.py) | Shared database schema helpers. |
| [app/website_monitor.py](BrowserApp/summit-web/app/website_monitor.py) | Website Monitor storage, technical checks, provider integrations, and scan comparisons. |

The pipeline coordinator is [lead_machine.py](BrowserApp/colorado-lead-machine/lead_machine.py). Discovery presets live in [lead_machine_search_config.py](BrowserApp/colorado-lead-machine/lead_machine_search_config.py), with provider enrichment in [enrichment.py](BrowserApp/colorado-lead-machine/enrichment.py) and [discovery_providers.py](BrowserApp/colorado-lead-machine/discovery_providers.py). Dedicated modules handle [presence resolution](BrowserApp/colorado-lead-machine/presence.py), [record checks](BrowserApp/colorado-lead-machine/colorado_records.py), [contact enrichment](BrowserApp/colorado-lead-machine/contact_enrichment.py), [scoring](BrowserApp/colorado-lead-machine/scoring.py), and [Excel reporting](BrowserApp/colorado-lead-machine/reporting.py).

## Development checks

Install the test dependencies in the same virtual environment:

```bash
python -m pip install pytest httpx
```

From the repository root, run these focused suites:

```bash
python -m pytest BrowserApp/colorado-lead-machine/test_presence_resolution.py BrowserApp/colorado-lead-machine/test_tech_stack_signals.py -q
python -m pytest BrowserApp/summit-web/test_website_monitor.py BrowserApp/summit-web/test_website_monitor_routes.py BrowserApp/summit-web/test_website_monitor_pages.py -q
python -m pytest BrowserApp/summit-web/test_local_security.py BrowserApp/lead-vault/test_scraper_network_security.py -q
node BrowserApp/summit-web/test_browser_security.cjs
```

The listed suites use test data and mocked network/provider responses. Avoid unrestricted test discovery: some files under `BrowserApp/lead-vault/` are live provider diagnostics that load local credentials or call external services when imported.
