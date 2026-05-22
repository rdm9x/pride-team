# Contributing to devboard

Thanks for thinking about helping out. `devboard` is a small open-source project — a local kanban driven by an AI dev team. We try to keep the contribution loop short: clone, fix, push, merge.

This guide covers everything you need to ship your first PR.

- [Code of conduct](#code-of-conduct)
- [Quick setup](#quick-setup)
- [Code style](#code-style)
- [Branching](#branching)
- [Conventional commits](#conventional-commits)
- [Adding a new role](#adding-a-new-role)
- [Adding a new LLM provider](#adding-a-new-llm-provider)
- [Testing](#testing)
- [Pull request process](#pull-request-process)
- [Where to ask questions](#where-to-ask-questions)

---

## Code of conduct

We follow the [Contributor Covenant v2.1](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). Be kind, assume good faith, and keep technical disagreements technical.

> **Note:** `CODE_OF_CONDUCT.md` is not yet committed to the repo. It is tracked as **TODO** under epic E4 (documentation pass) and will land before the v1.0 tag. Until then, the linked Contributor Covenant text is the canonical reference.

To report a problem, email **owner@example.com** or open a private GitHub issue.

---

## Quick setup

You will need:

- **Python 3.11+**
- **git**
- **An LLM provider.** Anthropic API key (recommended), OpenAI key, or local Ollama. The Team Lead currently runs on Claude via the `claude` CLI; see [`docs/adr/0001-llm-provider.md`](docs/adr/0001-llm-provider.md) for the multi-provider plan.

Clone the repo and create a virtualenv:

```bash
git clone https://github.com/rdm9x/devboard.git
cd devboard

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
```

Install dependencies. The repo is split into two packages — `mcp_сервер` (the MCP kanban server) and `дашборд` (the Flask UI):

```bash
pip install -e ./mcp_сервер[dev]
pip install -e ./дашборд[dev]
```

> **Note:** There is no top-level `requirements-dev.txt` yet — dev extras live in each package's `pyproject.toml` under `[project.optional-dependencies.dev]`. A unified `requirements-dev.txt` is **TODO** for E4 and will pin everything in one place.

Run the test suite:

```bash
pytest
```

You should see green output across `mcp_сервер/tests/` and `smoke/tests/`. If it fails on a clean clone, that is a bug — please open an issue.

Start the dashboard to see your changes:

```bash
./команды/devboard-start.sh
open http://127.0.0.1:4999
```

---

## Code style

We use **[ruff](https://docs.astral.sh/ruff/)** for linting and formatting. Configuration lives in each package's `pyproject.toml`:

```toml
[tool.ruff]
line-length = 100
target-version = "py311"
```

Before you push:

```bash
ruff check .
ruff format .
```

### Pre-commit hooks

The repo ships a [`.pre-commit-config.yaml`](.pre-commit-config.yaml) with the baseline hooks every PR is expected to pass:

- `end-of-file-fixer`, `trailing-whitespace`, `check-yaml`, `check-toml`, `check-merge-conflict`, `check-added-large-files` (500 KB cap) — from [`pre-commit/pre-commit-hooks`](https://github.com/pre-commit/pre-commit-hooks).
- `ruff check --fix` and `ruff format` — from [`astral-sh/ruff-pre-commit`](https://github.com/astral-sh/ruff-pre-commit). Configuration is picked up from each package's `pyproject.toml` (line-length 100, `py311`).
- `mypy` is included as a commented-out template. Enable it once a top-level mypy config lands.

One-time setup after cloning:

```bash
pip install pre-commit
pre-commit install
```

From then on every `git commit` runs the hooks on staged files. To lint the whole repo on demand (and the same command CI runs):

```bash
pre-commit run --all-files
```

If a hook auto-fixes a file (`ruff --fix`, `end-of-file-fixer`), the commit aborts so you can review the diff — re-stage the change and commit again.

### Style conventions

- Type-annotate public functions. `def fn(x: int) -> str:`, not `def fn(x):`.
- Prefer `dataclass(frozen=True)` for value objects.
- Async only where it pays off (I/O, streaming). Don't wrap CPU loops in `async def`.
- Keep modules under ~300 lines. Split before they grow.
- Tests live next to the package: `mcp_сервер/tests/`, `дашборд/tests/`.

---

## Branching

We branch from `main` and merge back into `main`. There are no long-lived release branches.

| Prefix | Use for | Example |
|---|---|---|
| `feature/` | New features | `feature/openai-provider` |
| `fix/` | Bug fixes | `fix/sqlite-lock-timeout` |
| `docs/` | Docs-only changes | `docs/contributing-guide` |
| `chore/` | Tooling, deps, CI | `chore/bump-ruff` |

Branch names: lowercase, hyphen-separated, descriptive. Avoid `feature/my-stuff` — pick a noun phrase that maps to the PR title.

Commit messages follow [Conventional Commits](#conventional-commits) (see next section). Reference the epic/task id in the subject or body when you have one (`feat(llm): add OpenAI provider (E6.2)`).

---

## Conventional commits

We use **[Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)** because release automation (`release-please`, see [`.github/workflows/release.yml`](.github/workflows/release.yml)) parses commit subjects on `main` to decide the next semver bump and to generate `CHANGELOG.md` entries.

### Format

```
<type>(<optional scope>): <short summary>

<optional body — what & why, not how>

<optional footer(s) — BREAKING CHANGE:, Refs:, Closes:>
```

Subject in **lowercase**, **imperative mood**, **no trailing period**, **≤ 72 chars**. Russian is allowed in the body but **keep the type and summary in English** so the changelog stays consistent.

### Types and what they do

| Type | Meaning | Version bump |
|---|---|---|
| `feat:` | New user-visible feature | **minor** (1.0.0 → 1.1.0) |
| `fix:` | Bug fix | **patch** (1.0.0 → 1.0.1) |
| `feat!:` / `fix!:` / `BREAKING CHANGE:` in body | Backwards-incompatible change | **major** (1.0.0 → 2.0.0) |
| `perf:` | Performance improvement, no behaviour change | patch |
| `refactor:` | Internal restructure, no behaviour change | none |
| `docs:` | Docs only | none |
| `test:` | Tests only | none |
| `chore:` | Tooling, deps, repo housekeeping | none |
| `build:` | Build system or packaging | none |
| `ci:` | CI config / workflows | none |
| `style:` | Formatting, whitespace | none |
| `revert:` | Reverts a previous commit | depends on what's reverted |

> Note: until the first major release after 1.0.0, `bump-minor-pre-major` is enabled in `release-please-config.json` — breaking changes still bump only the **minor** while we are stabilising the API. That flag will be removed when we cut the first 2.x.

### Scope (optional)

A short noun describing the area touched: `llm`, `dashboard`, `mcp`, `roles`, `ci`, `docs`. Pick one — don't list multiple. If a change spans the whole repo, drop the scope.

### Examples

```text
feat(llm): add OpenAI provider with tool-call ID normalization

Implements the LLMProvider contract from ADR-001 for OpenAI's chat-completions
API. Maps tool_call_id <-> Anthropic-style toolu_* IDs via a session map.

Refs: E6.2
```

```text
fix(mcp): release fcntl lock on abnormal exit

The stale .lock file could persist after SIGKILL and block the next startup.
Cleanup now runs in an atexit + signal handler.

Closes: #42
```

```text
feat(dashboard)!: rename /api/v1/tasks to /api/v2/tasks

BREAKING CHANGE: clients pinned to /api/v1/tasks must migrate to /api/v2.
The v1 endpoint returns 410 Gone until removal in 3.0.0.
```

```text
docs: add Conventional Commits section to CONTRIBUTING
```

```text
chore(deps): bump ruff from 0.6.9 to 0.7.0
```

### What happens after you push

1. `release.yml` runs on every push to `main`.
2. `release-please` reads commit subjects since the last tag and either opens or updates a release-PR titled `chore(main): release X.Y.Z`. The PR bumps `version.txt` and rewrites the `[Unreleased]` section of `CHANGELOG.md` to `[X.Y.Z] - YYYY-MM-DD`.
3. When a maintainer merges that release-PR, `release-please` creates an annotated tag `vX.Y.Z` and a GitHub Release whose body is taken from the new changelog section.
4. Direct pushes to `main` that contain only `docs:` / `chore:` / `test:` / `refactor:` / `ci:` commits won't trigger a bump — the release-PR will sit and wait until a `feat:` or `fix:` lands.

### Quick local check

The repo doesn't enforce conventional commits with a hook yet (planned: `commitlint` under E5). For now, eyeball your subject against the table above before pushing. If you got the type wrong, fix it with `git commit --amend` while the commit is still in your branch — once it's on `main`, only a follow-up `revert:` or a hand-edit of the release-PR can fix the changelog.

---

## Adding a new role

Roles are the heart of `devboard`. Each role is a system prompt in `роли/<role>.md` with YAML frontmatter, loaded by the Team Lead and handed to a Claude subagent through the `Task` tool.

### 1. Create the file

```bash
touch роли/myrole.md
```

### 2. Add frontmatter

The role file format is fixed by **ADR-002 — Role format** (see [`docs/adr/0002-role-format.md`](docs/adr/0002-role-format.md)).

> **Note:** ADR-002 has not been published yet. Until it lands, follow the existing roles (`роли/бэкенд.md`, `роли/qa.md`) as a template. The frontmatter contract below is the de-facto standard the project uses today.

Minimum frontmatter:

```yaml
---
тип: системный_промт_роли
роль: myrole
проект: devboard
дата_создания: 2026-05-21
описание_короткое: |
  One-sentence description of what this role does and when the Team Lead
  should delegate to it.
# Optional — picks the LLM provider per ADR-001. Defaults to auto-detect.
llm: claude            # claude | openai | ollama
model: opus            # provider-specific alias
temperature: 0.2
---
```

### 3. Write the prompt body

After the frontmatter, write the system prompt in Markdown. Cover:

- **Specialization** — what this role is good at.
- **Tools** — which MCP / Read / Write / Bash tools it should use.
- **Boundaries** — what it must not touch.
- **Workflow** — read task, do work, `add_comment` for progress, `submit_result` at the end.

Use existing roles as templates. Match their tone and section structure so the Team Lead's pattern-matching keeps working.

### 4. Wire it into the Team Lead

The Team Lead (`роли/тимлид.md`) lists the roles it knows about. Add your role to that list and to the README's role table.

### 5. Test it in the local kanban

```bash
# Start the dashboard
./команды/devboard-start.sh

# Create a small task targeted at your new role through the UI,
# then click "Run team" and watch the live log.
```

The role should pick up the task, post at least one `add_comment`, and call `submit_result` with `new_status="review"`. If it loops or stalls, your prompt is probably missing a boundary — tighten it and retry.

### 6. Document it

- Add a row to the role table in [`README.md`](README.md).
- If the role needs new env-vars or tools, document them in `README.md` → Configuration.

---

## Adding a new LLM provider

`devboard` is moving from hard-coded `claude` CLI calls to a pluggable `LLMProvider` abstraction. The contract is locked in **[ADR-001 — LLMProvider interface](docs/adr/0001-llm-provider.md)**. Read it before you start — it explains why we use the Anthropic message format, how tool-call IDs are normalized across providers, and how MCP bridging works for non-Claude backends.

The short version:

### 1. Subclass `LLMProvider`

```python
# llm/myprovider.py
from llm.base import LLMProvider, LLMResponse, LLMChunk, Message, Tool

class MyProvider(LLMProvider):
    async def invoke(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ) -> LLMResponse:
        ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[Tool] | None = None,
        system_prompt: str | None = None,
    ):
        ...
```

### 2. Map your provider's format to the Anthropic-style contract

- `Message` is Anthropic-shaped: `role` ∈ `{"user", "assistant"}`, `content` is either a string or a list of `TextBlock | ToolUseBlock | ToolResultBlock`.
- Tool-call IDs must be normalized to Anthropic style (`toolu_*`). Keep a session-scoped `_id_map` for the reverse mapping when you send `tool_result` back. See ADR-001 §3 ("Tool-call ID-несовместимость").
- Stream chunks must be one of `TextDelta | ToolUseStart | ToolUseDelta | ToolUseEnd | MessageStop`.

### 3. Register the provider

Add your provider to `create_provider()`:

```python
# llm/factory.py
def create_provider(config: dict) -> LLMProvider:
    name = config.get("llm") or _auto_detect()
    if name == "myprovider":
        from llm.myprovider import MyProvider
        return MyProvider(**config)
    ...
```

Import lazily inside the branch — users who don't need your provider should not have to install your SDK.

### 4. Handle MCP

MCP-tools are not part of the `LLMProvider` contract. For non-Claude providers, expose MCP-tools to the model by injecting their JSON schemas into the system prompt and parsing the model's JSON tool-call output yourself. See ADR-001 §6.1.

### 5. Test it

Add a smoke test under `smoke/tests/` that:

- Sends a single-turn `invoke()` and asserts non-empty text response.
- Sends a tool-using prompt and asserts a `ToolUseBlock` in `response.content`.
- Iterates `stream()` end-to-end and asserts the expected chunk sequence.

Run with a mock backend in CI; run against the real provider locally and paste the output in the PR description.

---

## Testing

### Unit tests — pytest

Every new module needs at least one test. Place tests next to the package they cover:

```
mcp_сервер/tests/test_<module>.py
дашборд/tests/test_<module>.py
smoke/tests/test_<scenario>.py
```

Pattern:

```python
def test_create_task_returns_id(tmp_path):
    db = tmp_path / "tasks.db"
    repo = TaskRepo(db)
    task_id = repo.create_task(title="foo", role="бэкенд")
    assert task_id
    assert repo.get_task(task_id).title == "foo"
```

Run a focused subset while iterating:

```bash
pytest mcp_сервер/tests/test_repo.py -k create_task -x -vv
```

Run everything before pushing:

```bash
pytest
```

### End-to-end tests — Playwright

For dashboard changes that touch the UI, add a Playwright spec under `дашборд/tests/e2e/`.

> **Note:** Playwright is not wired up yet — tracked under E4 / E5. When it lands, the convention will be:

```bash
pip install playwright pytest-playwright
playwright install chromium
pytest дашборд/tests/e2e/
```

Until then, manual smoke through the dashboard (create task → run team → accept) is acceptable evidence in the PR description.

### What CI runs

CI is **planned for E6** (GitHub Actions). Once live, every PR will run:

- `ruff check .`
- `pytest` across all packages
- Playwright e2e (when available)

Until CI is green by default, paste your local `pytest` output in the PR description.

---

## Pull request process

1. **Fork** the repo (or create a branch if you are a maintainer).
2. **Branch** from `main` using a `feature/` / `fix/` / `docs/` prefix.
3. **Commit** in small, reviewable chunks. One concern per commit.
4. **Open the PR** against `main`. Use a short title (`E6.2: add LLMProvider base class`) and fill in:
   - **What** — one-paragraph summary.
   - **Why** — link the epic, ADR, or issue.
   - **How tested** — `pytest` output, screenshots, or manual steps.
5. **CI must be green.** If it is red, fix the build before requesting review.
6. **One approval** from a maintainer is required to merge.
7. **Squash merge.** We keep `main` history linear. Your commits get squashed into a single commit using the PR title as the subject — so make that title good.

### Review checklist (what reviewers look for)

- Code matches the style above (`ruff` clean, type-annotated).
- New behaviour has a test.
- Public surface changes are documented (README, ADR, or a docs/ file).
- No secrets, API keys, or `.env` files committed.
- Bash commands in docs actually run on a clean clone.

If your PR is a work-in-progress, open it as a **draft** and prefix the title with `WIP:`. Maintainers won't review drafts unless you ping them.

---

## Where to ask questions

- **Bugs and feature requests** — [GitHub Issues](https://github.com/rdm9x/devboard/issues). Search first; reproduce in 3-5 lines.
- **Design discussion** — [GitHub Discussions](https://github.com/rdm9x/devboard/discussions). Good for "should we…" questions before you write code.
- **Security disclosures** — email **owner@example.com**. Do not open a public issue for vulnerabilities.

For larger changes (new role, new provider, refactor that crosses package boundaries), open a Discussion or a draft ADR under `docs/adr/` first. It saves everyone time.

---

Thanks again for reading this far. Ship the PR.
