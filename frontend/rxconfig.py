import os

import reflex as rx

# Perf: Reflex's backend auto-reload watcher defaults to watching the whole cwd
# (this directory), which includes .web/node_modules -- tens of thousands of
# generated/vendored files that never need a backend restart. Scope it to just
# the actual Python app source. Relative path (not absolute): the underlying
# env var splits on ":", which collides with Windows drive letters (D:\...).
os.environ.setdefault("REFLEX_HOT_RELOAD_OVERRIDE_PATHS", "aj360_app")

config = rx.Config(
    app_name="aj360_app",
    # C4 defense-in-depth: bind the backend API to loopback by default so the
    # production-agent endpoints aren't exposed on all interfaces. Override with
    # REFLEX_BACKEND_HOST=0.0.0.0 for container/remote deployments.
    backend_host=os.getenv("REFLEX_BACKEND_HOST", "127.0.0.1"),
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="inherit", accent_color="bronze",
                           gray_color="sand", radius="large", scaling="100%"),
        ),
    ],
)
