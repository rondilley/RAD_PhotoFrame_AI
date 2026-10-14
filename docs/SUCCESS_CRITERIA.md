# Success Criteria: RAD_PhotoFrame_AI

Author: Claude for Ron Dilley.

Date: 2026-10-13. Status: draft, revised after the Phase 6 review
(`.ai-reviews/20261013-143624/synthesis.md`) and the Phase 8 review
(`.ai-reviews/20261013-145421/synthesis.md`).

Companion documents: [VISION](VISION.md), [REQUIREMENTS](REQUIREMENTS.md),
[ARCHITECTURE](ARCHITECTURE.md).

Each criterion has an ID, a measure and a threshold. REQUIREMENTS §0.2 gives
the milestone gate for each criterion. Section 3 connects each
criterion to its test. Section 4 gives the proof that does not count.

## 1. Business success criteria

These criteria come from the principals in VISION §3.

| ID | Criterion | Measure | Threshold | Version |
| --- | --- | --- | --- | --- |
| BC-01 | Ron gets the state of the week from the frame. | Ron's entry in a daily log (`tasks/usage_log.md`): "read the frame, did not open the sources" yes or no. | Yes on 8 of 10 workdays in two sequential weeks. | v0.4 |
| BC-02 | The frame procedure does not damage the frame. | The frame boots to the kiosk. A restore of the full backup into a disk image file on the host gives the same SHA-256 as the backup. A restore to the frame is not part of this test. It must have its own approval from Ron. (AI review 20261013-143624: openai.) | Both conditions are correct at the end of the frame slices. | v0.1 |
| BC-03 | Confidential Reflex data stays on the workstation. | Audit of the DR-04 rule: a search of the repository, the `.ai-reviews/` bundles and the host logs for Reflex text. | Zero Reflex text found. | v0.1 |
| BC-04 | Maintenance does not use Ron's time. | Minutes of manual repair each week, from the daily log. | 15 minutes or less in each of two sequential weeks. | v0.4 |
| BC-05 | A new dashboard type is fast to add. | The work for one new dashboard type after v0.1. | One work session, and zero changed lines in the core package. | vNext |
| BC-06 | The adapters keep the data current with no repair. | The count of adapter runs that end with a parse fault, from the OR-01 log. (AI review 20261013-143624: gemini.) | Zero parse faults in two sequential weeks. Or, each fault shows on its panel in less than its data age limit. | v0.4 |

## 2. Technical success criteria

### 2.1 Frame

| ID | Criterion | Threshold | Requirements |
| --- | --- | --- | --- |
| TC-01 | Root ADB through USB without the AiMOR channel. | `adb -d shell id` gives `uid=0(root)` after three power cycles. | FR-05 |
| TC-02 | The vendor channel is off. | `pm list packages -d` contains the three vendor packages, and `netstat -an` shows no `:7806` after a reboot. | FR-04, FR-06, SR-02 |
| TC-03 | The recovery path works. | Ron opens Android Settings from the kiosk by hand, with one finger, three times in sequence. | FR-07 |
| TC-04 | The backup is good. | All FR-02 checks are satisfactory. | FR-02 |
| TC-05 | The frame has no open network port. | Scan from a home LAN device and from an IoT VLAN device: `nmap -Pn -sS -p-` (all TCP ports) and `nmap -Pn -sU --top-ports 200`. A port with the result "open" is a failure. Ron records "open or filtered" UDP results and examines them on the frame with `netstat -anu`. (AI review 20261013-143624: openai.) | SR-01, SR-03, TR-03 |
| TC-06 | WebView gate. | `dumpsys package com.android.webview` gives 106.0.5249.126 and a dashboard shows correctly. If not, the frame shows the PNG mode (FR-17), and Ron records the decision. | FR-08, FR-17 |
| TC-07 | VLAN preflight. | Do this test before the frame connects to Wi-Fi. A test device on the IoT VLAN cannot connect to TCP 7806 on an external host. It can connect only to the dashboard port on the workstation. (AI review 20261013-143624: openai.) | FR-04, SR-01, SR-02 |

### 2.2 Reliability and performance

| ID | Criterion | Threshold | Requirements |
| --- | --- | --- | --- |
| TC-10 | Soak. | 72 hours with no manual action and with the daily reload off. Kiosk memory stays less than 150 MB PSS at each hourly sample. (AI review 20261013-145421: gemini.) | NFR-03, TR-05 |
| TC-11 | Recovery. | After each of 5 frame power cycles and 3 host restarts, a dashboard shows again in less than 3 minutes. | NFR-05 |
| TC-12 | Long run. | 14 days in sequence without manual repair. | VISION §7 |
| TC-13 | Data age. | At 20 random times during the soak, each panel's data age is less than its NFR-04 limit. | NFR-04 |
| TC-14 | Page size. | Each dashboard page with its assets is less than 300 KB. | NFR-02 |
| TC-15 | Browser features. | The feature test finds zero features that Chromium 106 does not support. | NFR-01, AR-03 |
| TC-16 | Collector cost. | Average CPU less than 5 percent of one core during one hour. | NFR-07 |
| TC-17 | Transcript reader speed. | First pass less than 120 s. Each subsequent pass less than 5 s. | NFR-06 |

### 2.3 Correct data

| ID | Criterion | Threshold | Requirements |
| --- | --- | --- | --- |
| TC-20 | Claude Code token totals are correct. | For three days, the dashboard totals agree to 1 percent with a second count. The second count comes from a different script that we write for the test, or from `ccusage`. | FR-20, IR-01 |
| TC-21 | Codex token totals are correct. | For three days, the totals agree to 1 percent with the sum of the `token_count` differences from a different script. | FR-21, IR-02 |
| TC-22 | Reflex text is correct. | For the two newest weeks, the frame text is the same as the source text. This includes the top 5 priorities, the action items and the day plan. A script compares them, and Ron looks at the frame. | FR-43 to FR-45 |
| TC-23 | Project data is correct. | For 5 projects, the newest VIBE_HISTORY date and the slice counts on the frame are the same as the files. | FR-24 |
| TC-24 | Faults show on the panel. | When the test renames a source file, its panel shows a fault state in less than its data age limit. | FR-15 |

### 2.4 Security

| ID | Criterion | Threshold | Requirements |
| --- | --- | --- | --- |
| TC-30 | Token check. | A request without the frame token gets HTTP 403. | SR-05 |
| TC-31 | CSP. | Each dashboard response has a Content-Security-Policy header that permits only the host origin. | SR-06 |
| TC-32 | No secrets on the frame. | A search of all page responses finds no key, token or OAuth value from the host. | SR-07 |
| TC-33 | Reflex allowlist. | The adapter refuses each SR-08 file, and the test shows the refusal. | SR-08, TR-04 |
| TC-34 | Read-only host. | During the soak, the host service writes files only in its cache folder and its log folder. | SR-09 |
| TC-35 | Host firewall. | The workstation refuses a connection to the host port from a home LAN device that is not the frame. | SR-04 |
| TC-36 | Kiosk origin pin. | A dashboard page with a link to a different origin, made for this test, does not open that origin in the kiosk. (AI review 20261013-143624: openai.) | SR-11 |

### 2.5 Maintainability and observability

| ID | Criterion | Threshold | Requirements |
| --- | --- | --- | --- |
| TC-40 | Plugin boundary. | The fifth dashboard adds files only in the adapters, templates and configuration. The core package diff is empty. | FR-18 |
| TC-41 | Health endpoint. | `/healthz` shows a last good run time for each configured source. | OR-02 |
| TC-42 | Heartbeat. | The system dashboard shows a frame heartbeat age of less than 120 s during the soak. | OR-03, FR-32 |

## 3. Test plan

| Criterion | Test | Data source | Threshold | Frequency |
| --- | --- | --- | --- | --- |
| TC-01 to TC-04 | Runbook steps T7 and T8, done by hand with Ron | The frame through USB | Section 2.1 | One time at the frame slices, and after each frame change |
| TC-07 | Connection test from a laptop on the IoT VLAN | Router, workstation | Section 2.1 | One time in v0.0, and after each router change |
| TC-05 | `nmap` TCP and UDP scan from two networks | The frame | Zero open ports | At the frame slices, and each month |
| TC-06 | `dumpsys package` | The frame | Section 2.1 | After the WebView slice |
| TC-10, TC-13, TC-16 | Soak script that samples `dumpsys meminfo`, `/healthz` and CPU | Frame and host | Section 2.2 | Before Ron closes v0.3, and before Ron closes v0.4 |
| TC-11 | Power-cycle test | Frame and host | Section 2.2 | Before Ron closes v0.1 |
| TC-12 | Daily log | Ron | 14 days | Before Ron closes v0.4 |
| TC-14, TC-15 | `pytest` asset test | Built pages | Section 2.2 | Each commit that changes a page |
| TC-17 | `pytest` speed test on the live transcripts | `~/.claude/projects` | Section 2.2 | Each change to the reader |
| TC-20, TC-21 | Comparison script | Live logs | 1 percent | Each change to a reader, and one time a week during v0.4 |
| TC-22 | Comparison script and a look at the frame by Ron | Live Reflex documents | Same text | Each change to the Reflex adapter, and each week during v0.4 |
| TC-23, TC-24 | `pytest` with the live files | `G:\git`, a renamed copy | Section 2.3 | Each change to an adapter |
| TC-30 to TC-35 | `pytest` and a scan from a LAN device | Host | Section 2.4 | Each change to the server, and before Ron closes each version |
| TC-40 | `git diff --stat` of the core package | Repository | Empty | When we add the fifth dashboard |
| BC-01, BC-04, BC-06 | Daily log and OR-01 log | Ron, host | Section 1 | Two weeks during v0.4 |
| BC-02 | Backup restore check | Backup image | Same SHA-256 | One time after the frame slices |
| BC-03 | Search for Reflex text | Repository, `.ai-reviews/`, host logs | Zero | Before Ron closes each version |

## 4. What does not count as success

The vibe-init standard requires this rule, word for word:

> “No iteration, MVP, or version is 'shipped,' 'closed,' or 'complete' until at least one real call against the real external service has returned data. Stub-based tests are wiring checks, not validation.”

For this project, these items do not count:

- **A dashboard in a desktop browser.** A version closes only when the frame
  shows the page. A desktop Chrome is newer than Chromium 106, and it hides
  feature and memory problems.
- **Tests with invented data.** Each adapter test reads the live sources on
  the workstation (TR-01). Sample data that a person or a model wrote is a
  wiring check only.
- **An `OKAY` from a write tool.** A write to the frame counts only after a
  readback shows the new data (rule R3).
- **ADB commands as proof of the recovery path.** `input tap` and `screencap` do
  not prove that Ron can get to Android Settings. Only Ron's finger on the
  panel proves it (rule R9).
- **"No errors in the log".** A panel with no data and no fault is a defect
  (FR-15).
- **A port scan from the workstation only.** The scan must come from the home
  LAN and from the IoT VLAN (TC-05).
- **A soak with the screen off or the kiosk in the background.** The soak
  counts only when the kiosk shows the dashboards for all 72 hours.
