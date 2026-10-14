import re
from datetime import date

from .config import CURRENCIES, MAX_MINOR
from .errors import DomainError

IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0,119}\Z")


def object_body(value):
    if not isinstance(value, dict):
        raise DomainError("INVALID_REQUEST", "Request body must be an object")
    return value


def identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise DomainError("INVALID_FIELD", f"{field} must be a nonempty identifier of at most 120 characters")
    return value


def text(value, field, maximum=140, default=""):
    if value is None:
        return default
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise DomainError("INVALID_FIELD", f"{field} must be printable text of at most {maximum} characters")
    return value


def currency(value):
    if not isinstance(value, str) or value not in CURRENCIES:
        raise DomainError("UNKNOWN_CURRENCY", "Currency must be EUR, USD, GBP, JPY or KWD")
    return value


def minor(value, field, positive=False):
    if type(value) is not int or abs(value) > MAX_MINOR or (positive and value <= 0):
        raise DomainError("INVALID_AMOUNT", f"{field} must be an integer in the supported monetary range")
    return value


def iso_date(value):
    try:
        parsed = date.fromisoformat(value)
    except (ValueError, TypeError):
        raise DomainError("INVALID_DATE", "Date must use YYYY-MM-DD") from None
    if parsed.isoformat() != value:
        raise DomainError("INVALID_DATE", "Date must use YYYY-MM-DD")
    return value


def page_integer(value, field, default, maximum=None):
    if value is None:
        return default
    try:
        result = int(value)
    except (ValueError, TypeError):
        raise DomainError("INVALID_QUERY", f"{field} must be an integer") from None
    if result < 0 or (maximum is not None and result > maximum):
        raise DomainError("INVALID_QUERY", f"{field} is outside the supported range")
    return result
