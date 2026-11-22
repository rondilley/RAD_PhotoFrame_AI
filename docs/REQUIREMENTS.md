# Requirements: RAD_PhotoFrame_AI

Author: Claude for Ron Dilley.

Date: 2026-10-13. Status: draft, revised after the Phase 6 review
(`.ai-reviews/20261013-143624/synthesis.md`) and the Phase 8 review
(`.ai-reviews/20261013-145421/synthesis.md`).

Companion documents: [VISION](VISION.md), [SUCCESS_CRITERIA](SUCCESS_CRITERIA.md),
[ARCHITECTURE](ARCHITECTURE.md),
[research survey](2026-10-13_PhotoFrame_Dashboard_Research.md),
[discovery notes](../tasks/discovery_notes.md).

## How to read this document

- Each requirement has an ID, one RFC 2119 keyword (MUST, SHOULD, MAY), a
  scope tag, and a source.
- Scope tags: **v0.0** to **v0.4** and **vNext**. Section 0.2 gives the
  milestones. VISION §5 gives the dates.
- Sources: `DN` is the discovery notes and `RS` is the research survey.
  `EX` is the example repository (`background/photo-frame-dashboard/`).
  `R1` to `R9` are the example repository rules (DN §6). `Ron` is an answer
  from Ron (DN §1 and §8.1). `AIR` is the Phase 6 review synthesis.

## 0. Context and scope

### 0.1 The two parts

RAD_PhotoFrame_AI has two parts:

1. **The frame procedure.** A runbook and scripts that get root on a PF1007L
   photo frame through USB, lock it down, and install a kiosk app.
2. **The host service.** A Python service on Ron's Windows 11 workstation. It
   reads local data sources and makes the dashboards. The frame requests the
   dashboards from the host through the IoT VLAN.

<!-- AI review 20261013-143624: gemini, openai, xai -->
### 0.2 Milestones

The milestones put the work that can damage the frame first, and the work
with confidential data after the lockdown of the frame.

| Version | Name | Contents | Exit gate |
| --- | --- | --- | --- |
| v0.0 | Preflight | Frame identity (firmware, eMMC size, USB IDs, WebView). Host tools (adb, JDK, Android build tools). VLAN and egress rules. No write to the frame. | DN OQ1 and OQ2 have answers. Ron selects the route, or the project stops. TC-07 is satisfactory. |
| v0.1 | Foundation | Root, backup, lockdown and kiosk on the frame. Host skeleton: one page with a clock and the system panel, token, CSP, heartbeat, health endpoint, version redraw, Chromium 106 asset test. WebView gate. | TC-01 to TC-07, TC-11, TC-14, TC-15, TC-30 to TC-32, TC-35, TC-36. A 24-hour frame run. |
| v0.2 | Vibe telemetry | Claude Code and Codex readers, project summary, rotation, plugin registry. | TC-17, TC-20, TC-21, TC-23, TC-24. |
| v0.3 | Reflex | Reflex JSON contract and docx fallback, allowlist and path rules, privacy switch, 72-hour soak. | TC-10, TC-13, TC-16, TC-22, TC-33, TC-34. |
| v0.4 | Daily use | Family dashboard (calendar, weather), night schedule, local LLM cluster, provider APIs. Each integration closes on its own gate. | TC-12, BC-01, BC-04, BC-06. |
| vNext | Growth | New dashboard types, HTTPS with a private CA, touch detail views. | TC-40, BC-05. |

<!-- AI review 20261013-143624: openai -->
### 0.3 Deployment assumptions

These are premises, not controls. If one changes, the requirements change.

- **A1.** The frame is in Ron's private office. Only Ron reads it.
- **A1b.** The frame is the only device on its VLAN or SSID.
- **A2.** Ron controls the router and the IoT VLAN, and can stop egress
  traffic from the frame.
- **A3.** The Windows workstation is trusted.
- **A4.** Only trusted persons can touch the frame.
- **A5.** There is no public cloud host and no public HTTPS endpoint.
- **A6.** The Wi-Fi uses WPA2 or WPA3. The threat model accepts plain HTTP on
  the IoT VLAN until vNext (SR-14).

<!-- AI review 20261013-143624: openai -->
### 0.4 What stays on the host

Credentials, source documents, collection logic and stored data stay on the
host. The host sends rendered dashboard content to the frame, and the frame
shows it. The frame does not store that content. This is the correct meaning of
"all data collection and secrets stay on the host" in `background/goal.md`.

## 1. Functional requirements (FR)

### 1.1 Frame procedure

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| FR-01 | The frame runbook MUST follow the PF1007L test sequence T1 to T8. It MUST stop at the first mismatch in a hash, model string, offset or size. | v0.0 | EX start-here, R4 |
| FR-02 | The runbook MUST make a full eMMC backup and check it (byte count, SHA-256, gzip readback, `0xCC` check, two independent reads) before the first write to the frame. | v0.1 | R2 |
| FR-03 | The runbook MUST get Ron's approval for each write to the frame, and MUST record the undo step before the write. | v0.1 | R1, R5 |
| FR-04 | The runbook MUST stop outbound frame traffic to the vendor ports before the frame connects to a network. The vendor ports are TCP 7806, TCP and UDP 10546 to 10550, and TCP and UDP 3478. | v0.0 | EX aimor-remote-root-shell §8 |
| FR-05 | Before it disables AiMOR, the runbook MUST get root ADB through USB without the AiMOR channel. It MUST show that this ADB stays after a power cycle. | v0.1 | R9, EX network-adb §6 |
| FR-06 | The runbook MUST disable `com.efercro.os.aimor`, `com.yhk.qeota` and `com.DeviceTest` only after Ron makes sure on the panel, by hand, that the kiosk opens Android Settings. | v0.1 | R9 |
| FR-07 | The kiosk app MUST have an escape to Android Settings that the `gslX680` touch panel can read with one finger. ARCHITECTURE gives the gesture. | v0.1 | EX network-adb §6, AIR S13 |
| FR-08 | The runbook SHOULD replace the stock WebView 44 with WebView 106.0.5249.126 from the pinned LineageOS prebuilt, with all three native libraries. The result of this step is the WebView gate (satisfactory or not satisfactory). | v0.1 | EX allwinner-a33-pf1007l §5 to §6 |
| FR-09 | The runbook SHOULD apply the PF1007L boot fixes (MAC pin, NTP server, deferred Wi-Fi start) so that the frame connects to Wi-Fi again after a power cycle with no touch. | v0.1 | EX pf1007l-boot-fixes |
| FR-10 | The runbook MUST keep a private record of each frame (setup, backups, changes, undo) in the ignored `frames/` folder. | v0.0 | R7, R8, EX frame-records |

### 1.2 Host service: core

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| FR-11 | The host service MUST run on the Windows 11 workstation. The frame MUST request each page from the host through HTTP. The host MUST NOT open a connection to the frame in usual operation. | v0.1 | Ron, AIR S2 |
| FR-12 | The host service MUST show the dashboards in turn. The configuration MUST set the display time and the active hours for each dashboard. | v0.2 | DN §4, RS §10 item 8 |
| FR-13 | Each dashboard MUST show the age of its data and the name and date of its source document or endpoint. | v0.1 | VISION bet 2 |
| FR-14 | The frame MUST redraw a dashboard only when the content version from the host changes. | v0.1 | RS §10 item 5 |
| FR-15 | When a source is not available, or a parse stops with an error, the panel MUST show a fault state with the cause. It MUST NOT show an empty panel. It MUST NOT show data from before the last refresh as current data. | v0.1 | VISION bet 2 |
| FR-16 | When the frame cannot get to the host, the kiosk MUST show a "host offline" screen and MUST try again automatically. | v0.1 | EX kiosk README |
| FR-17 | If the WebView gate (FR-08) is not satisfactory, the host service MUST make a PNG of each dashboard, and the frame MUST show the PNG. Then this requirement goes into v0.1. | v0.1 contingency | RS §10 item 4, AIR C2 |
| FR-18 | The core capabilities are file reads, HTTP GET with a time limit, SQLite key-value state and the host key files. A new dashboard that uses only these MUST be one source adapter, one panel template and one configuration entry. It MUST NOT change the core service. (AI review 20261013-145421: openai.) | v0.2 | VISION bet 4 |
| FR-19 | The host service SHOULD put the frame in night black mode (black screen, lowest backlight) and back at configured hours. (AI review 20261013-145421: openai.) | v0.4 | DN OQ11, RS §10 item 9 |

### 1.3 Vibe-coding dashboard

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| FR-20 | The dashboard MUST show Claude Code token use for today and for the last 7 days, by model and by project, from the local transcripts in `~/.claude/projects`. | v0.2 | Ron, DN §3.5 |
| FR-21 | The dashboard MUST show Codex token use for today and for the last 7 days, and the rate-limit percentage, from the rollout logs in `~/.codex/sessions`. | v0.2 | Ron, RS V4.4 |
| FR-22 | The dashboard MUST show the Claude Code and Codex sessions that wrote to their log in the last 15 minutes, with their project. | v0.2 | DN §4 |
| FR-23 | The dashboard SHOULD show the Claude Code five-hour and seven-day rate-limit percentage from the status line data. | v0.2 | RS V4.3 |
| FR-24 | The dashboard MUST show the VIBE projects that changed most recently. For each, it MUST show the date and title of the newest `VIBE_HISTORY.md` entry and the slice count (done and total) from `tasks/todo.md`. | v0.2 | DN §3.5, DN OQ8 |
| FR-25 | For each project in that list, the dashboard SHOULD show the date of the last commit. It SHOULD also show the count of files with changes that are not committed. | v0.2 | DN OQ8 |
| FR-26 | The dashboard SHOULD show the estimated cost of the Claude Code token use, and MUST label it as an estimate. | v0.4 | RS V4.1 |
| FR-27 | The dashboard SHOULD show for each local LLM endpoint its health, its model, its token rate and its active slots (llama-server `/metrics`, `/slots` and `/health`, Ollama `/api/ps`, vLLM `/metrics`). | v0.4 | Ron, RS V4.6 |
| FR-28 | The dashboard MAY show organization usage and cost from the Anthropic and OpenAI admin APIs when the host has admin keys. | v0.4 | Ron, RS V4.5 |

### 1.4 System dashboard

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| FR-30 | The dashboard MUST show the CPU load, the memory use and the disk space of the workstation. It MUST show the load, memory, temperature and power of the GPU. | v0.1 | DN §4 |
| FR-31 | The dashboard SHOULD show the same values for the local LLM cluster hosts. It SHOULD also show the NPU use and the top GPU process of each host. The source is a read-only SSH session that reads `/proc` and `/sys`. The hosts do not run Glances (changed 2026-11-22). | v0.4 | RS V4.7, Ron |
| FR-32 | The dashboard MUST show when the frame last sent a heartbeat to the host. | v0.1 | OR-03 |

### 1.5 Reflex dashboard

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| FR-40 | The Reflex adapter MUST read only the files that match these patterns below the configured Reflex root: `dashboard/*_reflex_dashboard.json`, `ToDo/*_Action_Items_Report*.docx`, `ToDo/*_Monday_Update.docx`, `ToDo/*_Marlow_Monday_Update_Section*.md`, `Notes/*_Weekly_Priorities.docx`, `Notes/*_Day_Plan.docx`, `Dashboards/*_reflex_platform_usage_dashboard.html`. | v0.3 | DN §3.4, Ron |
| FR-41 | The configuration MUST set the Reflex root folder. The default is `~/Desktop/Reflex_Security`. | v0.3 | Ron |
| FR-42 | The adapter MUST use the newest JSON file when its date is the same as or newer than the newest docx or md file. Else, for each document type, it MUST use the newest file by the date in the file name. For two files with the same date, it MUST use the `_refreshed` file. | v0.3 | DN §3.4, Ron |
| FR-43 | The dashboard MUST show the "today in one line" text and the time table from the Day Plan. If the Day Plan date is not today, it MUST show the Day Plan date clearly. | v0.3 | Ron, DN §3.4 |
| FR-44 | The dashboard MUST show "the week in one line" and the top 5 priorities from the Weekly Priorities. | v0.3 | Ron, DN §3.4 |
| FR-45 | The dashboard MUST show the "Today" and "This Week" action items with their due times from the Action Items Report. | v0.3 | Ron, DN §3.4 |
| FR-46 | The dashboard SHOULD show the wins, the risks, the exercises of this week and the biggest blocker from the Weekly Priorities and the Marlow section. | v0.3 | DN §3.4 |
| FR-47 | The dashboard MAY show the headline metrics from the newest platform usage dashboard. | v0.4 | DN §3.4 |
| FR-48 | When the newest document of a type is older than 8 days, the dashboard MUST mark that panel as out of date. | v0.3 | VISION bet 2 |
| FR-49 | The project MUST supply a JSON schema for the Reflex dashboard data and a step for the weekly workflow that writes `dashboard/YYYY-MM-DD_reflex_dashboard.json`. The project MUST NOT change the weekly workflow without Ron's approval. (AI review 20261013-143624: gemini. Decision by Ron.) | v0.3 | AIR C5, Ron |

### 1.6 Family dashboard

v0.1 has a clock only. The family dashboard with calendar and weather is v0.4.

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| FR-50 | The host page MUST show the time and the date in the America/Los_Angeles time zone. | v0.1 | Ron |
| FR-51 | The family dashboard MUST show the weather forecast for a configured location from Open-Meteo. | v0.4 | Ron, RS V2 |
| FR-52 | The family dashboard MUST show the events of today and tomorrow from the configured Google calendars. | v0.4 | Ron |

## 2. Non-functional requirements (NFR)

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| NFR-01 | Each dashboard page MUST use only the HTML, CSS and JavaScript features that Chromium 106 supports, and MUST NOT use a JavaScript framework. Until a test on the frame shows that `:has()` works, pages MUST NOT use it. | v0.1 | RS §10 item 3, RS §11 |
| NFR-02 | The total size of each dashboard page with its CSS, scripts and fonts MUST be less than 300 KB. | v0.1 | RS V2.3 |
| NFR-03 | The memory of the kiosk app on the frame MUST stay less than 150 MB PSS after 72 hours of operation. | v0.3 | EX kiosk about 80 MB |
| NFR-04 | Data age limits: active sessions 60 s, token totals 5 minutes, host metrics 30 s, Reflex documents 15 minutes after a new file arrives. | v0.1 | VISION §7 |
| NFR-05 | After a power cycle of the frame or a restart of the host, the frame MUST show a dashboard again in less than 3 minutes. It MUST do this with no touch. | v0.1 | VISION §7 |
| NFR-06 | The transcript readers MUST read only new data after the first pass. The first pass MUST end in less than 120 s, and each subsequent pass in less than 5 s. | v0.2 | DN §3.5 (136 MB) |
| NFR-07 | The collectors MUST use less than 5 percent of one CPU core as an average on the workstation. | v0.3 | DN §3.1 |
| NFR-08 | Primary values MUST have a minimum text height of 24 px, and body text a minimum of 18 px, at the frame density of 160. | v0.1 | RS V5.4 |
| NFR-09 | Each dashboard MUST move its content by 2 to 6 px on a schedule of 60 s or less. | v0.1 | RS V2.6, EX ambient.js |
| NFR-10 | Each dashboard MUST answer one primary question first. Section 2.1 gives the questions. Other data goes to a secondary area or to the source reference. (AI review 20261013-143624: openai.) | v0.1 | RS V5.2, AIR S6 |

### 2.1 The primary question of each dashboard

| Dashboard | Primary question |
| --- | --- |
| Vibe | Which sessions are active, and which limit is near? |
| Projects | Which projects changed, and which project has a stop? |
| Reflex today | What must Ron do today? |
| Reflex week | What are the priorities of the week? |
| System | Which part has a problem? |
| Family | What is the time, the weather and the next event? |

## 3. Security requirements (SR)

| ID | Requirement | Scope | Source |
| --- | --- | --- | --- |
| SR-01 | The frame MUST connect only to the IoT VLAN. The firewall MUST let the frame open connections only to the dashboard port on the workstation. | v0.0 | Ron, RS §10 item 2 |
| SR-02 | The router MUST stop all traffic from the frame to the vendor ports in FR-04 at all times. | v0.0 | EX aimor-remote-root-shell §8 |
| SR-03 | During usual operation, the frame MUST NOT listen on a TCP or UDP port, TCP 5555 and TCP 8086 included. Maintenance ADB goes through USB. | v0.1 | RS V6.1 |
| SR-04 | The host service MUST listen only on the workstation address. The Windows firewall MUST let only the frame-only VLAN subnet get to its port. When the frame has a DHCP reservation, the rule MUST let only the frame address connect. These two controls are the primary access control. (AI review 20261013-145421: gemini.) | v0.1 | RS V6.4, AIR C3 |
| SR-05 | The host service MUST reject each request that does not have the configured frame token. The kiosk MUST send the token in a cookie, not in the URL. The token is a secondary control, because a person with root on the frame can read it. The runbook MUST change the token after each physical maintenance session. (AI review 20261013-143624: gemini, openai, xai.) | v0.1 | RS V6.4, AIR C3 |
| SR-06 | Each dashboard page MUST send a Content-Security-Policy that permits only the host origin. | v0.1 | RS §10 item 1 |
| SR-07 | The host service MUST NOT send an API key, admin key, OAuth token or a token of a different device to the frame in a page. | v0.1 | VISION bet 1 |
| SR-08 | The Reflex adapter MUST resolve the Reflex root to its canonical path. It MUST refuse symlinks, junctions, reparse points and paths that go out of the root. It MUST compare file names only in the FR-40 folders. Before it opens a file, it MUST refuse files in `Benefits/` or `Paystubs/`, and files with "w9", "Invoice" or "Agreement" in the name (letter case ignored). (AI review 20261013-143624: openai.) | v0.3 | DN §3.4, AIR C5 |
| SR-09 | The host service MUST only read its data sources. It MUST NOT write to the Reflex folder, to `G:\git` projects, to `~/.claude` or to `~/.codex`. | v0.1 | VISION §6 |
| SR-10 | The repository MUST ignore `*.key.txt`, `frames/`, `backups/`, `diagnostics/` and the host cache folder. | v0.0 | R7 |
| SR-11 | The kiosk app MUST NOT have a JavaScript bridge, and MUST open only the configured host origin. | v0.1 | RS V7.2 |
| SR-12 | Each file that the runbook downloads MUST have a pinned SHA-256 that the runbook checks before use. | v0.0 | R6 |
| SR-13 | The host service MUST have a privacy switch that removes the Reflex dashboard from the rotation immediately. It MUST have a test when assumption A1 is not correct. (AI review 20261013-143624: openai.) | v0.3 | RS V5.5, AIR S12 |
| SR-14 | In v0.1 to v0.4 the host service MAY use plain HTTP on the IoT VLAN with assumption A6. In vNext it SHOULD use HTTPS with a private CA and a certificate that the kiosk pins. (AI review 20261013-143624: openai. Decision by Ron.) | v0.1 | AIR S4, Ron |
| SR-15 | If the frame Wi-Fi does not stay connected for the 24-hour v0.1 run, the project SHOULD use USB-only mode: Wi-Fi off, `adb reverse` from the host, and a host watchdog that sets the reverse rule again after each reconnect. (AI review 20261013-143624: xai.) | v0.1 contingency | RS V6.5, AIR C4 |

## 4. Integration requirements (IR)

| ID | System | Requirement | Scope |
| --- | --- | --- | --- |
| IR-01 | Claude Code transcripts | The reader MUST parse JSONL line by line and MUST ignore unknown fields. When the last line has no line end, the reader MUST read it again in the subsequent pass. It MUST count each assistant message only one time. | v0.2 |
| IR-02 | Codex rollout logs | The reader MUST use the `token_count` events, which hold cumulative totals, and MUST calculate the differences from them. | v0.2 |
| IR-03 | Reflex documents | The reader MUST parse the JSON, `.docx` and `.md` files. It MUST mark a legacy `.doc` file as "format not available" and use the newest file in a format that it can read. It MUST read the platform usage HTML as text only and MUST NOT run its scripts. | v0.3 |
| IR-04 | llama-server | The reader MUST show HTTP 503 from `/health` as "loading", not as "down". It MUST NOT send a request that wakes a model that sleeps. | v0.4 |
| IR-05 | Anthropic and OpenAI admin APIs | When there is no admin key, the panel MUST show "not configured" and MUST NOT show an error. Each request MUST have a time limit of 10 s. | v0.4 |
| IR-06 | Open-Meteo | The reader MUST use the public API with no key, and MUST keep the last good forecast for a maximum of 6 hours. | v0.4 |
| IR-07 | Google Calendar | The reader MUST use OAuth with the `calendar.readonly` scope. The token MUST stay on the host. | v0.4 |
| IR-08 | ADB through USB | Maintenance scripts MUST find the frame by its USB ID and serial, and MUST stop when an identity check of DN §3.2 gives a different value. | v0.0 |
| IR-09 | Glances | The reader MUST use REST API version 4 with a time limit of 5 s for each request. | v0.4 |
| IR-10 | NVIDIA GPU | The reader MUST use `nvidia-ml-py` and MUST show "no GPU data" when NVML is not available. | v0.1 |

## 5. Data requirements (DR)

| ID | Requirement | Scope |
| --- | --- | --- |
| DR-01 | Classes: Reflex content is confidential. AI usage and project data is internal. Family data is personal. | v0.1 |
| DR-02 | The host service MUST NOT write Reflex content to disk. It MAY keep it in memory. | v0.3 |
| DR-03 | The host service MUST keep usage totals in a SQLite file in the ignored cache folder, for 400 days. | v0.2 |
| DR-04 | The project MUST NOT send Reflex content, transcript content or usage records to an external service, the multi-AI reviewers included. | v0.0 |
| DR-05 | The host service MUST record time in UTC and MUST show time in America/Los_Angeles. | v0.1 |
| DR-06 | The repository MUST NOT contain frame dumps, serials, MAC addresses, Wi-Fi data or vendor APKs. | v0.0 |
| DR-07 | Screen captures and logs that can show Reflex content MUST stay in the ignored `diagnostics/` folder. They MUST NOT go into an issue, a review bundle or a model prompt. The project MUST delete them when the slice that made them closes. (AI review 20261013-143624: openai.) | v0.3 |

## 6. Observability requirements (OR)

| ID | Requirement | Scope |
| --- | --- | --- |
| OR-01 | Each collector run MUST write one JSON log line with the source, the time, the duration, the item count and the error (if any). The log line MUST NOT contain Reflex content. | v0.1 |
| OR-02 | The host service MUST have a `/healthz` endpoint that shows the time of the last good run of each source. | v0.1 |
| OR-03 | The frame page MUST send a heartbeat to the host each 60 s or more frequently, with the content version on the screen. The `/v1/now` poll is the heartbeat. (AI review 20261013-145421: openai.) | v0.1 |
| OR-04 | The runbook MUST add one line to `frames/<unit>/changes.jsonl` for each change to the frame. | v0.0 |

## 7. Operational requirements (OPR)

| ID | Requirement | Scope |
| --- | --- | --- |
| OPR-01 | The project MUST have a frame runbook (`docs/FRAME_RUNBOOK.md`) and a host operations guide (`docs/OPERATIONS.md`). | v0.0 |
| OPR-02 | The host service MUST start automatically at Ron's logon and MUST start again after a crash. | v0.1 |
| OPR-03 | One command MUST build the kiosk APK and install it on the frame through USB. | v0.1 |
| OPR-04 | The runbook MUST give the recovery path back to Android Settings and the path back to the stock firmware from the backup. | v0.1 |

## 8. Architectural requirements (AR)

| ID | Requirement | Scope |
| --- | --- | --- |
| AR-01 | The frame MUST contain no dashboard logic. The host makes each page. | v0.1 |
| AR-02 | Each source adapter MUST give a typed snapshot. Templates MUST use only snapshots, and MUST NOT read sources. | v0.1 |
| AR-03 | A test MUST find CSS and JavaScript features that Chromium 106 does not support in the dashboard assets. | v0.1 |
| AR-04 | A configuration file MUST contain the dashboards, their adapters and their schedule. | v0.1 |
| AR-05 | When FR-17 applies, the PNG renderer MUST run in its own worker process. | v0.1 contingency |
| AR-06 | The host service MUST be one Python service process and, when FR-17 applies, one PNG worker process. It MUST NOT use a database server or a container. (AI review 20261013-143624: openai.) | v0.1 |

## 9. Maintainability requirements (MR)

| ID | Requirement | Scope |
| --- | --- | --- |
| MR-01 | The code MUST use Python 3.12 or newer, type hints, `ruff` and a `pyproject.toml`. | v0.1 |
| MR-02 | When a Reflex document format changes, the repair MUST change only one adapter file and its tests. | v0.3 |
| MR-03 | The project rules in `.claude/` MUST name this project, not LocalLLMPerf_AI. | v0.0 |

## 10. Testing requirements (TR)

| ID | Requirement | Scope |
| --- | --- | --- |
| TR-01 | Each adapter MUST have tests that read live source files on the workstation. Tests MUST NOT copy Reflex or transcript content into the repository. | v0.1 |
| TR-02 | Each slice that changes a page MUST show the page on the frame and record an `adb exec-out screencap` image in the ignored `diagnostics/` folder, as DR-07 specifies. | v0.1 |
| TR-03 | A security test MUST scan the frame from the home LAN and from the IoT VLAN. It MUST show no open frame port and no connection to TCP 7806. | v0.1 |
| TR-04 | A test MUST show that the Reflex adapter refuses each file and path in SR-08. | v0.3 |
| TR-05 | A soak test MUST run the frame and the host for 72 hours, and MUST record the kiosk memory each hour. | v0.3 |
| TR-06 | A test MUST load each dashboard in Chromium and MUST find no console error. | v0.1 |

## 11. Out of scope

| Item | Reason | Re-entry point |
| --- | --- | --- |
| Photo slideshows | Ron chose clock, calendar and weather for the family dashboard. | Ron requests it (vNext). |
| Smart-home controls, cameras, door alerts | Not a control surface (VISION §6). | None planned. |
| Claude Code logs from other hosts | Ron did not select this source. | vNext, with a small agent on each host. |
| Linux on the frame | No PF1007L port (RS §10 item 10). | None planned. |
| Fully Kiosk Browser | A second remote root channel (RS V7.2). | None planned. |
| Python on the frame | Ron chose a host service. | None planned. |
| Public HTTPS or a cloud host | Confidential data stays on the workstation (assumption A5). | None planned. |
| Pull requests to the upstream repository | Optional for Ron (VISION §3). | Ron makes the decision for each finding. |
| More than one frame | One office, one reader (VISION §6). | vNext. |
