# Vision: RAD_PhotoFrame_AI

Author: Claude for Ron Dilley.

Date: 2026-10-13. Status: draft, revised after the Phase 6 review
(`.ai-reviews/20261013-143624/synthesis.md`).

Companion documents: [REQUIREMENTS](REQUIREMENTS.md),
[SUCCESS_CRITERIA](SUCCESS_CRITERIA.md), [ARCHITECTURE](ARCHITECTURE.md),
[research survey](2026-10-13_PhotoFrame_Dashboard_Research.md),
[discovery notes](../tasks/discovery_notes.md).

## 1. The vision

By the end of January 2027, a PF1007L photo frame from Amazon is on the wall
of Ron's private office. It shows the state of Ron's work at a glance. The
frame is rooted, the vendor software is off, and the frame is a display only.
A Python service on Ron's Windows 11 workstation collects the data and makes
each dashboard.

The frame shows these dashboards in turn:

- The AI work in progress, local and remote.
- The status of the projects in `G:\git`.
- The health of the AI hosts.
- The Reflex Security week: the plan for today, the priorities for the week,
  the action items, and the customer delivery.
- A family dashboard with a clock, a calendar and the weather, after work
  hours. Until v0.4, this is a clock only.

Ron does not open a file, a terminal or a browser to know the status of the
work.

## 2. Why this approach

The status data of Ron's work is available today, but it is in many sources:

- Each week, AI workflows write five Reflex documents in three formats
  (docx, md, html) to `~/Desktop/Reflex_Security` (discovery notes §3.4).
- Claude Code and Codex record the token use of each session in local logs
  (discovery notes §3.5).
- 65 VIBE projects in `G:\git` record their state in `VIBE_HISTORY.md` and
  `tasks/todo.md`.
- The local LLM cluster has metrics endpoints. No person reads them when no
  benchmark runs.

To know the state of the week, Ron must open each source. A status display
that collects these sources removes that work. The alternatives cost more or
do less:

| Alternative | Why not |
| --- | --- |
| A second monitor with a browser tab | It uses a workstation screen, and a tab behind other windows is not a glance. The frame also stops when the workstation stops, but it is always in view on the wall. (AI review 20261013-143624: openai.) |
| A Raspberry Pi and a display | More parts, more cost, and one more device to maintain. The PF1007L has a 10.1-inch IPS touch screen, a stand and Wi-Fi in one unit (example repository README: "buy a $50 frame"). |
| An e-ink panel (TRMNL type) | Good for slow data. Too slow and too small for four dashboards that change during the day. |
| An Echo Show or a tablet | A locked platform, or a high cost for a fixed wall display. |
| A hosted dashboard service | The Reflex documents are confidential. The documents and the credentials must stay on Ron's workstation. |

The frame is also a known device. The wesbos photo-frame-dashboard community
recorded the PF1007L in detail, with a tested procedure to get root and a
kiosk app (research survey §2.2).

## 3. Principal map

| Principal | Role | What is important to them |
| --- | --- | --- |
| Ron Dilley | Owner, builder, and the only reader of the work dashboards | One glance gives the state of AI work, projects, hosts and the Reflex week. The frame must not make the home network less safe. Setup and repair must not use Ron's time each week. |
| Ron's household | People who use the family dashboard | A correct clock, calendar and weather. |
| Reflex Security (Marlow and team) | Owner of the business data on the Reflex dashboard | The Reflex documents (funding, pipeline, client names, names of persons) stay on Ron's workstation. Their rendered text shows only in Ron's private office. |
| The photo-frame-dashboard community | Source of the hardware procedure | Ron can send new PF1007L findings back as pull requests, with private data removed. This is optional. |

## 4. The strategic bets

### Bet 1: the frame is an untrusted display, and all logic is on the host

- **Claim.** The frame shows pages from one host origin. It holds no keys, no
  tokens for external services, no source documents and no business logic.
  It shows rendered content, which can be confidential, and it does not store
  that content (REQUIREMENTS §0.4). <!-- AI review 20261013-143624: openai -->
- **Why this is correct.** The PF1007L runs an `eng` build with SELinux
  disabled, root ADB without authentication, and a vendor remote root
  channel. Its last WebView (106) has 32 known exploited Chrome bugs that newer
  versions repair (research survey §10, items 1 and 2). A device like
  this must not hold secrets.
- **Risk.** Touch controls or offline operation can make logic on
  the frame necessary.
- **Mitigation.** The kiosk page sends touch events to the host, and the host
  makes the decision. When the host is off, the frame shows a clear "host
  offline" screen.

### Bet 2: the data comes from the work that Ron does today

- **Claim.** No dashboard has new data entry. Each panel reads documents and
  logs that Ron's work makes today: Reflex weekly documents, AI logs, project
  files and host metrics.
- **Why this is correct.** Ron's AI workflows make the weekly Reflex set
  (discovery notes §3.4). A display that needs manual updates becomes
  incorrect in some weeks.
- **Risk.** The Reflex document formats change. They changed in
  August 2026. Then a parser can stop without an error.
- **Mitigation.** Each source adapter records the date of the newest document
  that it read, and the dashboard shows that date. A parse failure shows as a
  fault on the panel, not as an empty panel.

### Bet 3: HTML from the server for a 2022 browser, with an image fallback

- **Claim.** The host makes plain HTML and CSS in the Chromium 106 feature
  set. If the WebView upgrade fails, the host sends a PNG of the same page.
- **Why this is correct.** Modern Python dashboard frameworks use a newer
  browser or more memory than a 1 GiB frame has (research survey §10, item 3).
  A PNG uses almost no browser features (research survey §10, item 4).
- **Risk.** A PNG has no touch targets. Screenshots on Windows add
  a headless browser to the host.
- **Mitigation.** HTML is the primary path. The PNG path is a fallback, and it
  runs in its own process.

### Bet 4: dashboards are plugins

- **Claim.** A new dashboard is one source adapter, one panel template and
  one line in the configuration.
- **Why this is correct.** Ron's request ends with "and other types". More
  dashboard types will come. If each new dashboard changes the core service,
  the project stops after the first four.
- **Risk.** A plugin interface that is too general costs more than
  it saves.
- **Mitigation.** The interface is the smallest one that the first four
  dashboards use. It becomes larger only when a fifth dashboard uses more.

### Bet 5: a glance, not a report

- **Claim.** Each dashboard shows only the data that Ron must know in two or three
  seconds. The full detail stays in the source documents.
- **Why this is correct.** Research on ambient displays recommends "just
  enough" information. Text with simple icons is the fastest to read
  (research survey §10, item 8).
- **Risk.** Ron can want more detail than a glance gives.
- **Mitigation.** Each panel shows the source of the full detail (file name
  and date). Touch can open a detail view in a subsequent version.

## 5. The arc

| Window | Name | Deliverables |
| --- | --- | --- |
| October to November 2026 | Foundation (v0.0 to v0.3) | The frame is rooted, backed up and locked down on the IoT VLAN. The vendor channel is off, and the recovery path is proved. Then the host service adds the system, vibe-coding and Reflex dashboards from live data, in that sequence. <!-- AI review 20261013-143624: gemini, openai, xai --> |
| December 2026 to January 2027 | Daily use (v0.4) | The family dashboard (Google Calendar, weather, clock). Panels for the local LLM cluster and provider usage. A night schedule. Two weeks of use without manual repair. |
| February 2027 and after | Growth (vNext) | New dashboard types when Ron requests them. Touch detail views. A second frame if Ron wants one. |

## 6. What this is not

- **Not a control surface.** The frame does not start, stop or change
  hosts, projects or Reflex systems.
- **Not a home automation hub.** There are no smart-home controls, cameras or
  door alerts from the example dashboard.
- **Not a Reflex reporting tool.** It reads Ron's weekly documents. It does
  not write, edit or send them.
- **Not a cloud service.** There is no hosted backend, no Cloudflare and no
  public URL.
- **Not a Linux port for the frame.** The frame stays on its Android build
  (research survey §10, item 10).
- **Not a general photo frame.** Photo slideshows are out of scope until Ron
  requests them.
- **Not for many users or remote viewers.** One frame, one office, one reader.
- **Not code on the frame.** The kiosk app and small root scripts are the only
  software that this project puts on the frame. Python runs on the host only.

## 7. Success at the horizon

At the end of January 2027:

- Ron reads the state of the week from the frame each workday. Ron does not
  open the source files to get it.
- The frame operated for 14 days in sequence without manual repair.
- Each dashboard shows data that is not older than its refresh limit, and it
  shows the age of its data.
- A port scan from the home network finds no open port on the frame. The
  frame has no network path to the vendor servers.
- Ron added a minimum of one new dashboard type after v0.1, with no change to
  the core service.
