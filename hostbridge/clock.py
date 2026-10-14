from datetime import datetime, timezone


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_instant(value):
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if instant.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return instant.astimezone(timezone.utc)


def business_date():
    return datetime.now(timezone.utc).date().isoformat()
