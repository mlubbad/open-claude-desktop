"""Marketplace plugin — word / character / line counts for a block of text."""
NAME = "word_count"
DESCRIPTION = "Count words, characters, and lines in a block of text."
CATEGORY = "Text"

TOOL = {
    "type": "function",
    "function": {
        "name": "word_count",
        "description": "Count the words, characters (with and without spaces), and lines "
                       "in the given text.",
        "parameters": {
            "type": "object",
            "properties": {"text": {"type": "string", "description": "The text to measure."}},
            "required": ["text"],
        },
    },
}


def run(args: dict) -> str:
    text = str(args.get("text", ""))
    words = len(text.split())
    # splitlines() honors \n, \r\n, \r and Unicode line boundaries; a trailing
    # terminator does not open an extra empty line.
    lines = len(text.splitlines())
    chars = len(text)
    no_spaces = sum(1 for c in text if not c.isspace())
    return (f"words: {words}\nlines: {lines}\ncharacters: {chars}\n"
            f"characters (no whitespace): {no_spaces}")
