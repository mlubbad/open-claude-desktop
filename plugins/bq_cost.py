"""BigQuery on-demand cost estimator plugin."""

NAME = "bq_cost"
DESCRIPTION = "Estimate BigQuery on-demand query cost from bytes scanned."

TOOL = {
    "type": "function",
    "function": {
        "name": "bq_cost",
        "description": "Estimate BigQuery on-demand cost for a query given the bytes "
                       "it scans. On-demand pricing is ~$6.25 per TiB (first 1 TiB/mo "
                       "free). Pass either `bytes` or `gb`.",
        "parameters": {
            "type": "object",
            "properties": {
                "bytes": {"type": "number", "description": "Bytes scanned."},
                "gb": {"type": "number", "description": "Gigabytes scanned (alt to bytes)."},
                "price_per_tib": {"type": "number",
                                  "description": "Override $/TiB (default 6.25)."},
            },
        },
    },
}

_TIB = 1024 ** 4


def run(args: dict) -> str:
    price = float(args.get("price_per_tib") or 6.25)
    if args.get("bytes") is not None:
        nbytes = float(args["bytes"])
    elif args.get("gb") is not None:
        nbytes = float(args["gb"]) * (1024 ** 3)
    else:
        return "Provide `bytes` or `gb`."
    tib = nbytes / _TIB
    cost = tib * price
    gib = nbytes / (1024 ** 3)
    return (f"{gib:,.2f} GiB ({tib:.4f} TiB) at ${price:.2f}/TiB "
            f"≈ ${cost:.4f} on-demand (excludes the monthly 1 TiB free tier).")
