"""Temporary hosted/public launch freeze for the Days 1-3 containment phase.

The product is safe to keep developing as a local loopback desktop application.  It is
not yet approved for a hosted, public-network, or multi-tenant deployment.  This module
is the single executable policy used by both backend startup and the release workflow.

Lifting the freeze intentionally requires a reviewed source change after the P0 launch
gates in ``docs/launch-freeze.md`` pass.  There is no environment-variable override.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence

from . import netguard, tenancy

DEPLOYMENT_MODE_ENV = "OCD_DEPLOYMENT_MODE"
DEFAULT_DEPLOYMENT_MODE = "local"
DEPLOYMENT_MODES = frozenset({"local", "desktop", "development", "hosted", "public"})
HOSTED_DEPLOYMENT_MODES = frozenset({"hosted", "public"})

# This is deliberately a source-controlled policy, not an environment toggle.  A code
# review that changes this constant is the auditable act that lifts the launch freeze.
HOSTED_PUBLIC_LAUNCH_FROZEN = True


def deployment_mode() -> str:
    """Return the declared deployment posture, defaulting to local-only."""
    return (os.getenv(DEPLOYMENT_MODE_ENV) or DEFAULT_DEPLOYMENT_MODE).strip().lower()


def launch_block_reason(host: str | None = None) -> str | None:
    """Explain why this process must not start, or return ``None`` when allowed.

    During the freeze, only loopback local/desktop/development use is generally allowed.
    Docker Compose may bind inside its container only when it declares ``development``
    *and* uses the existing loud insecure-network opt-in; Compose publishes that port on
    host loopback, so this carve-out is not approval for a public deployment.
    """
    mode = deployment_mode()
    if mode not in DEPLOYMENT_MODES:
        expected = ", ".join(sorted(DEPLOYMENT_MODES))
        return (f"Refusing to start: unknown {DEPLOYMENT_MODE_ENV}={mode!r}; "
                f"expected one of: {expected}.")

    if not HOSTED_PUBLIC_LAUNCH_FROZEN:
        return None

    if tenancy.enforcing():
        return ("Refusing to start: hosted/public launch is frozen and multi-tenant "
                "mode (OCD_MULTI_TENANT) is not approved.")

    if mode in HOSTED_DEPLOYMENT_MODES:
        return (f"Refusing to start: hosted/public launch is frozen; deployment mode "
                f"{mode!r} is not approved.")

    resolved_host = netguard.bind_host() if host is None else host
    if not netguard.is_loopback(resolved_host):
        dev_container = mode == "development" and netguard.allow_insecure_network()
        if not dev_container:
            return ("Refusing to start: hosted/public launch is frozen and a non-loopback "
                    f"bind ({resolved_host!r}) is not approved. Use loopback for local "
                    "development; the Compose dev stack must explicitly declare "
                    "OCD_DEPLOYMENT_MODE=development.")

    return None


def assert_launch_allowed(host: str | None = None) -> None:
    """Fail backend startup when the temporary launch policy rejects this process."""
    reason = launch_block_reason(host)
    if reason:
        raise RuntimeError(reason)


def main(argv: Sequence[str] | None = None) -> int:
    """Release-workflow policy check; non-zero means publishing stays blocked."""
    parser = argparse.ArgumentParser(description="Open Claude Desktop launch policy")
    parser.add_argument("--check-public-release", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.check_public_release:
        parser.error("--check-public-release is required")
    if HOSTED_PUBLIC_LAUNCH_FROZEN:
        print(
            "Public release blocked: hosted/public launch is FROZEN. "
            "See docs/launch-freeze.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through main() in tests
    raise SystemExit(main())
