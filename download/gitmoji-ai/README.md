<div align="center">

# 🤖 GitMoji AI

### AI-powered commit messages & changelog generator

**Never write a bad commit message again.**

[![PyPI](https://img.shields.io/pypi/v/gitmoji-ai?color=green&label=PyPI)](https://pypi.org/project/gitmoji-ai/)
[![Python](https://img.shields.io/pypi/pyversions/gitmoji-ai?label=Python)](https://pypi.org/project/gitmoji-ai/)
[![Tests](https://img.shields.io/github/actions/workflow/status/sochiautoparts/gitmoji-ai/ci.yml?label=Tests)](https://github.com/sochiautoparts/gitmoji-ai/actions)
[![License](https://img.shields.io/github/license/sochiautoparts/gitmoji-ai?label=License)](LICENSE)
[![Stars](https://img.shields.io/github/stars/sochiautoparts/gitmoji-ai?style=social)](https://github.com/sochiautoparts/gitmoji-ai)

[Installation](#-installation) • [Quick Start](#-quick-start) • [Features](#-features) • [GitHub Action](#-github-action) • [Pro](#-pro-version) • [Contributing](#-contributing)

</div>

---

## 🎬 Demo

```bash
$ gmai commit

📊 Diff Analysis

  Files changed: 3
  Lines added: +47
  Lines removed: -12
  Summary: Changed 3 file(s): new feature, bug fix

🤖 Generating AI commit suggestions...

💡 Commit Suggestions
┏━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━┓
┃ # ┃ Message                                 ┃ Confidence ┃
┡───╇──────────────────────────────────────────╇────────────┩
│ 1 │ feat(auth): add JWT token validation     │ 95%        │
│ 2 │ ✨ add JWT token validation to auth      │ 90%        │
│ 3 │ feat(auth): implement JWT validation     │ 85%        │
│   │ with refresh token support and expiry    │            │
│   │ checking for enhanced security           │            │
└───┴──────────────────────────────────────────┴────────────┘

Select commit [1/2/3/e(q)dit/(q)uit]: 1

✅ Committed! feat(auth): add JWT token validation
```

---

## ✨ Features

| Feature | Free | Pro |
|---------|:----:|:---:|
| AI commit messages | 50/month | ∞ |
| AI changelog generation | 3/month | ∞ |
| Conventional Commits | ✅ | ✅ |
| Emoji commits | ✅ | ✅ |
| Multi-language (6+ languages) | ✅ | ✅ |
| Git hook integration | ✅ | ✅ |
| GitHub Action | ✅ | ✅ |
| No watermark | ❌ | ✅ |
| Custom commit styles | ❌ | ✅ |
| Team features | ❌ | ✅ |
| Priority support | ❌ | ✅ |

---

## 📦 Installation

```bash
# With pip
pip install gitmoji-ai

# With pipx (recommended for CLI tools)
pipx install gitmoji-ai

# With uv
uv tool install gitmoji-ai
```

---

## 🚀 Quick Start

### 1. Set your OpenAI API key

```bash
export GMAI_OPENAI_API_KEY="sk-your-key-here"
```

Get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys) — costs ~$0.15 per 1M tokens.

### 2. Initialize in your repo

```bash
cd your-project
gmai init
```

This creates `.env` and installs a git hook that suggests commit messages automatically.

### 3. Make a commit

```bash
# Stage your changes
git add .

# Generate AI commit message and commit
gmai commit

# Or with auto-staging
gmai commit --stage

# Or just use git normally — the hook will suggest!
git commit
```

### 4. Generate changelog

```bash
# Auto-generate from recent commits
gmai changelog --version v1.2.0

# Output to file
gmai changelog --version v1.2.0 --output CHANGELOG.md

# Russian language
gmai changelog --version v1.2.0 --lang ru
```

---

## 🎮 Commands

| Command | Description |
|---------|-------------|
| `gmai commit` | 🤖 Generate AI commit message and commit |
| `gmai changelog` | 📝 Generate AI changelog |
| `gmai init` | 🔧 Initialize GitMoji AI in repo |
| `gmai info` | 📊 Show repo info & usage stats |
| `gmai pro activate KEY` | ⭐ Activate Pro license |
| `gmai pro status` | 🔍 Check Pro license status |
| `gmai pro purchase` | 💳 Get Pro license |

### Commit options

```bash
gmai commit --style emoji       # Emoji-style commits: ✨ add login
gmai commit --style plain       # Plain: add login functionality
gmai commit --style conventional # Conventional: feat(auth): add login (default)
gmai commit --lang ru           # Russian: feat(auth): добавить логин
gmai commit --stage             # Auto-stage all changes
gmai commit --sign              # GPG-sign the commit
gmai commit --yes               # Skip confirmation, use first suggestion
gmai commit --path ./my-repo    # Specify repo path
```

### Changelog options

```bash
gmai changelog --version v2.0.0          # Version tag
gmai changelog --format angular          # Angular format
gmai changelog --lang ru                 # Russian changelog
gmai changelog --since v1.0.0            # Only changes since tag
gmai changelog --no-ai                   # Manual grouping (no AI)
gmai changelog --output CHANGELOG.md     # Write to file
```

---

## 🤖 GitHub Action

Use GitMoji AI in your CI/CD pipeline:

```yaml
name: Auto Changelog

on:
  push:
    branches: [main]

jobs:
  changelog:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: sochiautoparts/gitmoji-ai/action@v1
        with:
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          generate-changelog: true
          version: v1.2.0
          language: en
```

Or use it as a PR checker:

```yaml
name: AI Commit Review

on:
  pull_request:

jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - uses: sochiautoparts/gitmoji-ai/action@v1
        with:
          openai-api-key: ${{ secrets.OPENAI_API_KEY }}
          language: en
```

---

## 🌍 Multi-language Support

| Language | Flag | Example |
|----------|------|---------|
| English | 🇬🇧 | `feat(auth): add login validation` |
| Russian | 🇷🇺 | `feat(auth): добавить валидацию логина` |
| Spanish | 🇪🇸 | `feat(auth): añadir validación de login` |
| German | 🇩🇪 | `feat(auth): login-validierung hinzufügen` |
| French | 🇫🇷 | `feat(auth): ajouter la validation du login` |
| Japanese | 🇯🇵 | `feat(auth): ログイン検証を追加` |
| Chinese | 🇨🇳 | `feat(auth): 添加登录验证` |

---

## ⭐ Pro Version

### Why upgrade?

- **∞ Unlimited** AI commits and changelogs
- **No watermark** — clean commit history
- **Custom styles** — create your own commit format
- **Team features** — shared settings and changelogs
- **Priority support** — faster responses

### Pricing

| Plan | Price | Best for |
|------|-------|----------|
| **Free** | $0 | Personal projects |
| **Pro** | $5/month | Professional developers |
| **Team** | $20/month | Teams & organizations |

Get Pro at [gitmoji-ai.dev/pricing](https://gitmoji-ai.dev/pricing)

```bash
# Activate Pro
gmai pro activate YOUR-LICENSE-KEY
```

---

## 🔧 Configuration

Create `.env` in your project root (or set environment variables):

```bash
# Required
GMAI_OPENAI_API_KEY=sk-your-key-here

# Optional
GMAI_DEFAULT_LANGUAGE=en          # Default commit language
GMAI_COMMIT_STYLE=conventional    # Default commit style
GMAI_OPENAI_MODEL=gpt-4o-mini    # AI model
GMAI_PRO_LICENSE_KEY=            # Pro license key
```

### Git Hook

After `gmai init`, every `git commit` will show AI suggestions in your editor:

```
# 🤖 GitMoji AI Suggestion:
# feat(auth): add JWT token validation
```

Just uncomment the line you like, save, and close the editor!

---

## 🏗️ Architecture

```
gitmoji-ai/
├── src/gitmoji_ai/
│   ├── cli.py          # Typer CLI interface
│   ├── ai_engine.py    # AI commit generation (OpenAI)
│   ├── git_ops.py      # Git operations (diff, commit)
│   ├── changelog.py    # Changelog generator
│   ├── config.py       # Configuration management
│   ├── usage.py        # Usage tracking & limits
│   └── suggest.py      # Quick suggest (for hooks)
├── action/
│   └── action.yml      # GitHub Action
├── .github/workflows/
│   ├── ci.yml          # CI pipeline
│   └── changelog.yml   # Auto changelog
├── tests/
│   └── test_core.py    # Test suite
└── pyproject.toml      # Project config
```

---

## 🤝 Contributing

Contributions are welcome! Please read our [Contributing Guide](CONTRIBUTING.md).

1. Fork the repository
2. Create your feature branch: `git checkout -b feat/amazing-feature`
3. Commit with GitMoji AI: `gmai commit` 😉
4. Push: `git push origin feat/amazing-feature`
5. Open a Pull Request

---

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.

---

<div align="center">

**Made with 🤖 and ❤️ by [GitMoji AI](https://github.com/sochiautoparts/gitmoji-ai)**

[⭐ Star on GitHub](https://github.com/sochiautoparts/gitmoji-ai) • [🐛 Report Bug](https://github.com/sochiautoparts/gitmoji-ai/issues) • [💡 Request Feature](https://github.com/sochiautoparts/gitmoji-ai/issues)

</div>
