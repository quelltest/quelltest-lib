# Configuration Reference

Quell is configured via `[tool.quelltest]` in `pyproject.toml` or a root-level `quell.toml`.

Run `quell init` to add the default configuration block.

## Core options

| Key | Default | Description |
|-----|---------|-------------|
| `llm_provider` | `"anthropic"` | LLM provider: `"anthropic"`, `"openai"`, or `"ollama"` |
| `llm_model` | `"claude-sonnet-4-5"` | Model name for the LLM provider |
| `ollama_base_url` | `"http://localhost:11434"` | Base URL for Ollama server |
| `max_verification_attempts` | `3` | Max attempts per requirement |
| `verification_timeout_seconds` | `30` | Timeout for each pytest subprocess run |
| `auto_write` | `false` | Write verified tests without interactive prompt |
| `audit_log_path` | `".quell/audit.jsonl"` | Path to the audit log |
| `backup_dir` | `".quell/backups"` | Directory for source file backups before write |
| `score_threshold` | `0.0` | Minimum quell score to pass `quell ci` |
| `diff_only` | `false` | Only scan files changed in the current git diff |

## Confidence score options (v1.0.0)

| Key | Default | Description |
|-----|---------|-------------|
| `ci_confidence` | `70` | Minimum confidence score to include a test in CI runs |

Override per-run: `quell check src/ --min-confidence 70 --ci-confidence 85`

## Spec reader toggles

| Key | Default | Description |
|-----|---------|-------------|
| `enable_docstring` | `true` | Read `Raises:` / `Returns:` blocks from docstrings |
| `enable_types` | `true` | Read Pydantic `Field` constraints and `Literal` types |
| `enable_mutations` | `false` | Read mutmut 3.x / Stryker survivor results |
| `enable_pyspark` | `false` | Read PySpark `StructType` schema constraints |

## Example

```toml
[tool.quelltest]
llm_provider = "anthropic"
llm_model = "claude-sonnet-4-5"
max_verification_attempts = 3
verification_timeout_seconds = 30
auto_write = false
ci_confidence = 70
```

## Environment variables

| Variable | Required for |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Anthropic provider |
| `OPENAI_API_KEY` | OpenAI provider |
| `QUELL_TRANSACTION_ROLLBACK` | Set automatically to `true` in container test runs |

Ollama requires no API key (runs locally).
