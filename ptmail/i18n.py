import gettext
from pathlib import Path

_translation = gettext.translation(
    "ptmail", Path(__file__).parent / "locale", fallback=True
)
_ = _translation.gettext


def plural(count, one, few, many):
    """Polska odmiana po liczbie, np. 1 załącznik, 2 załączniki, 5 załączników."""
    if count == 1:
        form = one
    elif count % 10 in (2, 3, 4) and count % 100 not in (12, 13, 14):
        form = few
    else:
        form = many
    return _(form).format(count=count)
