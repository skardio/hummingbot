"""Evidence Engine - deterministic performance adjudication.

The engine answers exactly one question: is there sufficient evidence that a
strategy, configuration or experiment performs better than its baseline?

Valid outcomes are ``PASS``, ``FAIL``, ``INSUFFICIENT_EVIDENCE``, plus the
procedural outcomes ``EXPLORATORY`` and ``ERROR``.

Design rules:

* Every threshold lives in ``config/evidence_policy.yaml``; none in Python.
* Database access is read-only, enforced technically.
* The verdict is decided in :mod:`tools.evidence.gate_engine` and nowhere else.

Reference documentation: ``docs/EVIDENCE_SCHEMA.md``.
"""

__all__ = [
    "bootstrap",
    "classify",
    "fingerprint",
    "gate_engine",
    "metrics",
    "policy",
    "reconcile",
]
