"""String helpers."""


def title_case(text: str) -> str:
    """Capitalise the first letter of every word, lower-case the rest."""
    return " ".join(word[:1].upper() + word[1:].lower() for word in text.split())
