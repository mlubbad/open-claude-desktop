# Hosted Multi-Tenant Containment Policy

**Desktop OSS Releases: ENABLED (`DESKTOP_RELEASE_FROZEN = False`)**  
**Hosted Multi-Tenant Cloud Mode: FROZEN (`HOSTED_PUBLIC_LAUNCH_FROZEN = True`)**

Single-user local loopback desktop builds (`.dmg`, `.msi`, `.AppImage`, `.deb`), CLI runs,
and loopback Docker Compose development stacks are enabled for community use.

Multi-tenant hosted server operation (`OCD_DEPLOYMENT_MODE=hosted|public`, `OCD_MULTI_TENANT=1`,
or unauthenticated non-loopback binds) fails closed through `backend/ocd_core/launchguard.py`.
