# pride-team — Twitter/X launch thread

**Audience:** indie devs / hackers / open-source folks on X. Skeptical of AI-coding hype.
**Tone:** dry, observational, no "🚀" or "game-changer". Concrete > generic.
**Length per tweet:** ≤ 280 chars (counted; emoji = 2 chars each).
**Media:** each tweet has a media placeholder describing what attaches.
**Publication:** Dmitry posts. Best window: Tue–Thu, 9–11 AM PT.

---

## Tweet 1/7 — hook
> I gave Claude a kanban board and seven roles (team lead, backend, QA, frontend, devops, architect, tech writer).
>
> One prompt went in. Five cards came out. A landing page shipped before lunch.
>
> Here's what actually happened.

**Char count:** 222/280
**Edit note:** dropped "and what broke" — the thread doesn't deliver an explicit failure mode, so the half-promise read as bait. Concrete numbers (seven, one, five) carry the hook on their own.
**Media:** [GIF, ~4s, looping: one card in Inbox → team lead decomposes → 5 child cards fan out into Todo, tagged by role. Sourced from video-script segments 6–7. Burnt-in captions off, cursor visible.]

---

## Tweet 2/7 — problem
> One chatbot. One long conversation. You've been here.
>
> Context window fills. No roles. No handoff. No "wait, don't push that to main."
>
> A team is not one session that scrolls forever. A team is people with different jobs and a board they share.

**Char count:** 244/280
**Media:** [Screenshot: a single ChatGPT-style chat with a long, faded scroll of messages — the familiar pain. Same shot as video-script segment 1.]

---

## Tweet 3/7 — solution
> So I built a kanban where each card is picked up by a separate Claude session with its own system prompt.
>
> Roles live as plain markdown in roles/*.md. Team lead reads the task, decomposes it, hands subtasks to the right specialist. Flask + SQLite + MCP underneath.

**Char count:** 264/280
**Media:** [Screenshot of the dashboard: Inbox · Todo · WIP · Review · Done columns, sidebar with 7 role chips visible. Annotate one chip ("backend") with a thin callout arrow.]

---

## Tweet 4/7 — killer feature: approval-gate
> ⚠ Anything destructive — git push, ssh, schema changes — stops at you.
>
> Red banner. Full diff. Two buttons: Approve, Reject.
>
> This isn't about autonomy. It's about trust. The agent does the boring 90%; you keep the keys to anything that leaves your machine.

**Char count:** 258/280 (incl. ⚠ counted as 2)
**Media:** [Screenshot of the approval modal: red banner "Needs your approval — git push origin main", full diff with syntax highlighting, Approve/Reject buttons. Same shot as video-script segment 12.]

---

## Tweet 5/7 — roles teaser
> Roles are just markdown files. You can fork them, edit them, share them.
>
> Five examples planned: PM, designer, security-auditor, code-reviewer, data-analyst. Import-by-URL after that.
>
> A small registry, not a platform. No accounts, no rent.

**Char count:** 236/280
**Edit note:** changed "already drafted" → "planned" — the five example roles (E7.5) are scheduled work, not yet on disk. Honest pre-launch.
**Media:** [Screenshot: roles/ directory listing in the file tree (тимлид.md, бэкенд.md, qa.md...), with one file open in the editor showing the top of a system prompt — title, persona, allowed tools.]

---

## Tweet 6/7 — open-source pitch
> v1.0 is Claude-only. MIT. Local. SQLite you can open with `sqlite3`. No telemetry, no cloud account, no sign-up.
>
> OpenAI and Ollama are on the roadmap, not in the box.
>
> Repo: github.com/<user>/pride-team
>
> Star if you want me to keep going.

**Char count:** 239/280
**Media:** [Terminal screenshot: `git clone github.com/<user>/pride-team && ./Start.command` running, ending with the localhost URL appearing. Same shot as video-script segment 17.]

---

## Tweet 7/7 — CTA / engage
> If you try it and it breaks, open a Discussion — I read every one and reply same day this week.
>
> Honest feedback over stars. Especially: what did you expect that wasn't there?
>
> Thread done. Back to the board.

**Char count:** 208/280
**Media:** [Short looping GIF, ~3s: the Done column filling with 5 green cards, slow zoom. Same shot as video-script segment 16. Optional: end-frame fades to repo URL.]

---

## Reply-to-thread engagement template

Pre-written replies for the three most likely comment types. Keep them short, friendly, link out — never defensive.

### Q1 — "How is this different from Claude Code / Aider / Cline?"
> Those are great single-loop agents — one session, one terminal. pride-team runs several sessions in parallel, each with a different role and a shared board, so handoffs survive context resets. Same Claude underneath, different shape around it. Architecture: github.com/<user>/pride-team/blob/main/ARCHITECTURE.md

### Q2 — "Does it work with OpenAI / Ollama?"
> Not in v1.0 — Claude-only for now because subagents and MCP are wired tight to the Anthropic SDK. OpenAI and Ollama are on the roadmap (E7); the LLMProvider interface lives in ADR-001 if you want to see the seam. Honest answer: 4–6 weeks if no one helps, faster with PRs.

### Q3 — "How do you stop it from going off the rails?"
> Two things. (1) Approval-gate: git push, ssh, anything destructive pauses with a full diff and waits for your click. (2) Roles are scoped — the QA bot literally cannot write to source, the tech writer cannot touch code. Both are configured in roles/*.md, no magic. Details: github.com/<user>/pride-team/blob/main/approval_gates.md

---

## Notes for the poster (Dmitry)

- Post tweet 1 as standalone first, then reply-chain 2–7 within 60 seconds (X penalizes long gaps between thread tweets in the algorithm).
- Repo URL placeholder `<user>` must be replaced before posting.
- After posting, pin tweet 1 to profile for 7 days.
- Reply to every comment within the first 4 hours — that window is where X decides whether to amplify the thread.
- If a reply gets > 20 likes, quote-tweet it from the project account with a thank-you. Compounds reach.
