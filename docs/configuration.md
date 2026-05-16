# Configuration Reference

Quell is configured via `[tool.quell]` in `pyproject.toml` or a root-level `quell.toml`.

Run `quell init` to add the default configuration block.

## Core options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `llm_provider` | str | `"groq"` | LLM provider: `"groq"`, `"anthropic"`, `"openai"`, or `"ollama"` |
| `llm_model` | str | `"llama-3.3-70b-versatile"` | Model name for the LLM provider |
| `use_llm` | bool | `false` | Opt-in LLM fallback for complex cases (requires `quell auth`) |
| `ollama_base_url` | str | `"http://localhost:11434"` | Base URL for Ollama server |
| `max_verification_attempts` | int | `3` | Max gate-pipeline attempts per requirement |
| `verification_timeout_seconds` | int | `30` | Timeout for each pytest subprocess run |
| `auto_write` | bool | `false` | Write tests without interactive prompt |
| `audit_log_path` | path | `".quell/audit.jsonl"` | Append-only write audit log |
| `backup_dir` | path | `".quell/backups"` | Source file backups before any write |
| `diff_only` | bool | `false` | Only scan files changed in the current git diff |

## v2.0.0 options

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `prs_threshold` | int | `60` | Minimum Production Readiness Score to pass `quell ci` |
| `scaffold_dir` | path | `"tests/scaffold"` | Directory for SCAFFOLDED test stubs |

## Spec reader toggles

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `enable_docstring` | bool | `true` | Read `Raises:` / `Returns:` blocks from docstrings |
| `enable_types` | bool | `true` | Read Pydantic `Field` constraints and `Literal` types |
| `enable_mutations` | bool | `false` | Read mutmut 3.x / Stryker survivor results |
| `enable_pyspark` | bool | `false` | Read PySpark `StructType` schema constraints |

## Example `pyproject.toml` block

```toml
[tool.quell]
llm_provider = "groq"
llm_model = "llama-3.3-70b-versatile"
use_llm = false
max_verification_attempts = 3
verification_timeout_seconds = 30
auto_write = false
prs_threshold = 60
scaffold_dir = "tests/scaffold"
enable_docstring = true
enable_types = true
enable_mutations = false
```

## Auth and LLM keys

The preferred key management path is `quell auth`:

```bash
quell auth set --provider groq --key sk-...
quell auth set --provider anthropic --key sk-ant-...
quell auth status
```

Keys are stored in the OS keyring where available (macOS Keychain, GNOME Keyring, Windows Credential Store), with an encrypted file fallback.

Environment variable fallback (for CI):

| Variable | Required for |
|----------|-------------|
| `GROQ_API_KEY` | Groq provider |
| `ANTHROPIC_API_KEY` | Anthropic provider |
| `OPENAI_API_KEY` | OpenAI provider |

## Migration from v1.0.0

| Old key | New key / status |
|---------|-----------------|
| `[tool.quelltest]` | `[tool.quell]` (both still read) |
| `llm_provider = "anthropic"` | default changed to `"groq"` |
| `score_threshold` | replaced by `prs_threshold` |
| `ci_confidence` | still works; now affects PRS rather than individual test gate |
