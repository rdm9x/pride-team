# pride-team — 90-second demo video script

**Format:** 90 seconds, 18 segments × 5s
**Aspect ratio:** 16:9 (YouTube/Twitter/embed in README) — also export 9:16 vertical cut for mobile/X
**Voiceover:** EN, calm, conversational, ~1 sentence per segment (≤ 2 if needed)
**Style:** real screen capture (no fake mockups). One human on screen briefly at start and end.
**Music:** subtle synth pad, no melody (we want to hear voice). Start 0:03, fade out at 0:88.
**Subtitles:** burnt-in EN captions, white sans-serif, bottom-center (auto-readable on mobile and on muted feeds — ~85% of social plays).
**Goal:** a developer who never heard of us understands the idea in 30s and clicks the repo link by 90s.

---

## One-line summary (for description / pinned tweet)

> A real kanban board where AI roles — team lead, backend, QA, frontend — pick up cards, ship code, and ask you to approve anything destructive. Local. Open source.

---

## Storyboard

| # | Time | On screen | Voiceover (EN) | B-roll / notes |
|---|------|-----------|----------------|----------------|
| 1 | 0:00–0:05 | Talking head, 1.5s, then cut to laptop screen showing a single ChatGPT-style chat with a long, fading scroll of messages. | "One chatbot. One long conversation. You've been here." | Hook — make the pain feel familiar. Keep talking head ≤ 1.5s. |
| 2 | 0:05–0:10 | Pan to a second monitor — the pride-team dashboard, empty kanban with columns: Inbox · Todo · WIP · Review · Done. | "What if your AI was a team — with a board?" | Slow horizontal pan, ~0.5s on each column. |
| 3 | 0:10–0:15 | Sidebar lights up: 7 role chips — team lead, backend, QA, architect, frontend, devops, tech writer. | "Seven roles. Each one a separate prompt, a separate session." | Hover cursor across chips, names visible. |
| 4 | 0:15–0:20 | Click "New task". Modal opens. Type "Build a landing page for our coffee shop". | "You drop a task in the Inbox." | Real typing, ~12 chars/sec. |
| 5 | 0:20–0:25 | Card appears in Inbox. Big "Run team lead" button pulses softly. | "Hit Run." | Cursor moves to button — beat. |
| 6 | 0:25–0:30 | Live stream window opens at bottom: "team lead: reading task… decomposing into 5 subtasks…" lines tick in. | "Team lead reads the brief and breaks it down." | Lines should look like real Claude streaming (typewriter, ~30 cps). |
| 7 | 0:30–0:35 | 5 child cards fan out into Todo, each tagged with a role: frontend, frontend, backend, qa, devops. | "Each subtask gets the right role." | Cards slide in with a gentle stagger. |
| 8 | 0:35–0:40 | Two cards jump to WIP simultaneously — frontend (HTML) and backend (Flask route). Two live-stream panels split-screen. | "They work in parallel — different sessions, different roles." | Show two streams clearly distinguishable. |
| 9 | 0:40–0:45 | Frontend card → Review. Card shows preview thumbnail of the rendered landing page. | "Frontend ships HTML and CSS." | Thumbnail = real screenshot, not placeholder. |
| 10 | 0:45–0:50 | QA card picks up: stream shows "running playwright… 3 tests passed." | "QA runs the tests." | Green check animation, no celebration sound. |
| 11 | 0:50–0:55 | A red banner slides down from the top: **"⚠ Needs your approval — git push origin main"**. | "Anything destructive stops at you." | Banner is unmissable but tasteful — no klaxon. |
| 12 | 0:55–1:00 | Hover the approval card. Expands to show: full diff, commit list, target branch. | "You see the full diff before anything leaves your machine." | Real diff with syntax highlighting. |
| 13 | 1:00–1:05 | Two buttons: **Approve** (green) and **Reject** (gray). Cursor hovers Approve. Click. | "Approve." | One word voiceover. Let the click breathe. |
| 14 | 1:05–1:10 | Push animation; card slides to Done with a checkmark. Live stream: "pushed to origin/main · sha 7b9ab7d". | "Done." | One word. Pause. |
| 15 | 1:10–1:15 | Browser tab opens — the landing page is live. Coffee-shop hero, hours, map. | (silence — let the page breathe) | 5s of nothing said is rare and powerful. Light page-load sfx only. |
| 16 | 1:15–1:20 | Cut back to the kanban — every column except Done is empty. 5 green cards stacked in Done. | "From one prompt to shipped — in one afternoon." | Slow zoom on the Done column. |
| 17 | 1:20–1:25 | Cut to terminal: `git clone github.com/<user>/pride-team && ./Start.command`. Two lines, then a localhost URL appears. | "Local. Open source. MIT." | Real commands, real output. No ellipses cheats. |
| 18 | 1:25–1:30 | End card: pride-team logo · `github.com/<user>/pride-team` · "Try it free". QR code top-right for mobile viewers. | "Link below. Build a team." | Hold the end card 2 full seconds before fade. |

---

## Voiceover transcript (clean, for the recording session)

> One chatbot. One long conversation. You've been here.
>
> What if your AI was a team — with a board?
>
> Seven roles. Each one a separate prompt, a separate session.
>
> You drop a task in the Inbox.
>
> Hit Run.
>
> Team lead reads the brief and breaks it down.
>
> Each subtask gets the right role.
>
> They work in parallel — different sessions, different roles.
>
> Frontend ships HTML and CSS.
>
> QA runs the tests.
>
> Anything destructive stops at you.
>
> You see the full diff before anything leaves your machine.
>
> Approve.
>
> Done.
>
> *(silence — let the landing page show itself)*
>
> From one prompt to shipped — in one afternoon.
>
> Local. Open source. MIT.
>
> Link below. Build a team.

**Total words:** ~95. Comfortable at 95–100 wpm.

---

## Recording checklist for Dmitry

**Screen capture**
- Resolution: 1920×1080 (16:9) or 2560×1440 if your camera supports it. Downscale in edit.
- Frame rate: 60 fps for smooth cursor motion.
- Tools: macOS `Screen Studio` (recommended — auto-zooms on cursor) or QuickTime + manual zoom.
- Cursor: keep large/highlighted cursor — Screen Studio handles this automatically.
- Hide: dock, menu bar clutter, browser bookmarks bar, any personal tabs.

**Audio**
- Mic: any USB condenser is fine (Blue Yeti / Shure MV7). Built-in is **not** fine.
- Acoustic: small room, soft furniture, mic 15 cm from mouth, pop filter or sock over mic.
- Record voiceover **separately** from screen — don't try to do both live. Re-record any line that has clicks/breaths.

**Pace**
- Whole video should feel calm. If you feel rushed, the viewer feels rushed.
- 1-second pause between sentences is fine. Don't cut all silence — leave breathing room.

**Demo prep**
- Seed the kanban with one new task only. Empty everything else before recording.
- Use a fake repo for the `git push` — don't show real keys or branch names.
- For segment 15 (live landing page) — pre-build the page once, then revert. During recording, you're replaying a known-good outcome, not gambling on the demo gods.

**Edit**
- Cut breaths and "uh"s ruthlessly.
- Don't speed up the cursor — it looks artificial. Trust the viewer.
- Burnt-in subtitles: generate with Descript / Whisper, then proofread.
- Export 2 versions: 16:9 master, 9:16 vertical (crop center, re-position kanban for portrait).

---

## What to put in the description / pinned post

```
pride-team — give your AI a kanban board and a team of roles.

A real kanban (Inbox · Todo · WIP · Review · Done) where each card is picked up by a separate Claude session running a specific role: team lead, backend, QA, architect, frontend, devops, tech writer. Anything destructive — git push, ssh, schema changes — pauses at an approval gate so you stay in control.

Local-first. SQLite. Flask. MCP. Open source under MIT.

Repo: github.com/<user>/pride-team
Docs: README + ARCHITECTURE.md in the repo
Discord / Discussions: see repo header

This is v1.0. Roadmap: multi-LLM (OpenAI, Ollama), role marketplace, English UI.
```

---

## Out of scope for this 90s

These are intentionally **not** in the video — save for follow-up content:

- The architecture diagram (Mermaid graph) — belongs in a longer dev.to post.
- The `roles/*.md` file format — belongs in the marketplace teaser video.
- Multi-LLM (Claude / OpenAI / Ollama) — own short clip later.
- Approval gates beyond `git push` (ssh, DROP TABLE) — implied by segment 11, not enumerated.

---

## Acceptance (self-check)

- [x] 18 segments, each ≤ 2 sentences of voiceover.
- [x] Total voiceover ~95 words at 95–100 wpm → fits 90s with breathing room.
- [x] Mobile-readable: subtitles specified, 9:16 vertical cut planned.
- [x] No fake mockups — real screen capture path described.
- [x] CTA appears in segments 17 and 18, plus QR for mobile.
- [x] Ready to hand to Dmitry for recording without further questions.
