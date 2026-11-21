"""Hosted/multi-tenant containment guard + desktop release policy check.

Local loopback desktop and CLI operation are supported and shippable via GitHub Releases.
Hosted, public-network, and multi-tenant server deployments remain gated behind a
source-controlled policy until distributed multi-tenant controls in ``docs/launch-freeze.md``
are enabled.
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

# Multi-tenant / public cloud server hosting remains gated by default.
HOSTED_PUBLIC_LAUNCH_FROZEN = True
# Single-user loopback desktop installers (.dmg / .msi / .AppImage / .deb) are approved for OSS release.
DESKTOP_RELEASE_FROZEN = False


def deployment_mode() -> str:
    """Return the declared deployment posture, defaulting to local-only."""
    return (os.getenv(DEPLOYMENT_MODE_ENV) or DEFAULT_DEPLOYMENT_MODE).strip().lower()


def launch_block_reason(host: str | None = None) -> str | None:
    """Explain why this process must not start, or return ``None`` when allowed."""
    mode = deployment_mode()
    if mode not in DEPLOYMENT_MODES:
        expected = ", ".join(sorted(DEPLOYMENT_MODES))
        return (f"Refusing to start: unknown {DEPLOYMENT_MODE_ENV}={mode!r}; "
                f"expected one of: {expected}.")

    if not HOSTED_PUBLIC_LAUNCH_FROZEN:
        return None

    if tenancy.enforcing():
        return ("Refusing to start: hosted multi-tenant mode (OCD_MULTI_TENANT) "
                "is frozen in this build.")

    if mode in HOSTED_DEPLOYMENT_MODES:
        return (f"Refusing to start: hosted/public server launch is frozen; deployment mode "
                f"{mode!r} is not approved.")

    resolved_host = netguard.bind_host() if host is None else host
    if not netguard.is_loopback(resolved_host):
        dev_container = mode == "development" and netguard.allow_insecure_network()
        if not dev_container:
            return ("Refusing to start: hosted/public server launch is frozen and a non-loopback "
                    f"bind ({resolved_host!r}) is not approved. Use loopback for local "
                    "development; the Compose dev stack must explicitly declare "
                    "OCD_DEPLOYMENT_MODE=development.")

    return None


def assert_launch_allowed(host: str | None = None) -> None:
    """Fail backend startup when the launch policy rejects this process."""
    reason = launch_block_reason(host)
    if reason:
        raise RuntimeError(reason)


def main(argv: Sequence[str] | None = None) -> int:
    """Release-workflow policy check for desktop installer builds."""
    parser = argparse.ArgumentParser(description="Desktop release & hosted launch policy")
    parser.add_argument("--check-public-release", action="store_true")
    args = parser.parse_args(list(argv) if argv is not None else None)
    if not args.check_public_release:
        parser.error("--check-public-release is required")
    if DESKTOP_RELEASE_FROZEN:
        print(
            "Public desktop release blocked by DESKTOP_RELEASE_FROZEN. "
            "See docs/launch-freeze.md.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
