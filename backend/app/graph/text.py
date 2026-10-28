import re

_WS = re.compile(r"\s+")
_EDGE = re.compile(r"^[\W_]+|[\W_]+$")


def clean(text: str) -> str:
    """Postgres rejects NUL bytes and pypdf can emit them."""
    return text.replace("\x00", "").replace("­", "")


def collapse(text: str) -> str:
    """Whitespace-collapsed, casefolded: PDF line breaks stop mattering."""
    return _WS.sub(" ", clean(text)).strip().casefold()


def normalize_name(name: str) -> str:
    return _EDGE.sub("", collapse(name))
