import reflex as rx

config = rx.Config(
    app_name="aj360_app",
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="inherit", accent_color="bronze",
                           gray_color="sand", radius="large", scaling="100%"),
        ),
    ],
)
