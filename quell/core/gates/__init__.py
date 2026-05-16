"""5-gate verification pipeline for generated tests.

Each gate exports check(test_code, ctx) -> GateResult.
Orchestration lives in verifier.py.

Gate 1  AST & import validity
Gate 2  Originality (fingerprint + n-gram + boilerplate)
Gate 3  Security (banned calls, network, env mutations)
Gate 4  Passes on correct code (subprocess)
Gate 5  Fails on violated code (subprocess)
"""
from quell.core.gates.gate1_ast import check as gate1
from quell.core.gates.gate2_originality import check as gate2
from quell.core.gates.gate3_security import check as gate3
from quell.core.gates.gate4_pass_correct import check as gate4
from quell.core.gates.gate5_fail_violated import check as gate5

__all__ = ["gate1", "gate2", "gate3", "gate4", "gate5"]
