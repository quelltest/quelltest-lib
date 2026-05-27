import pytest
from pathlib import Path
from quell.sdk import Quell, ScoreResult, VerifyResult
from quell.core.models import QuellConfig

def test_quell_init_default():
    q = Quell()
    assert q.config.llm_provider == "anthropic"
    assert q.root == Path(".").resolve()

def test_quell_init_custom_config():
    config = QuellConfig(
        llm_provider="none",
        enable_docstring=False,
        enable_types=False,
        enable_mutations=True,
    )
    q = Quell(config=config)
    assert q.config == config
    assert q.config.llm_provider == "none"
    assert not q.config.enable_docstring
    assert not q.config.enable_types
    assert q.config.enable_mutations
