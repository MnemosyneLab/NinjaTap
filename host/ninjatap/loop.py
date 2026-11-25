"""One closed step: an element id, a tap at its center, then a new screenshot."""

from ninjatap.client import Phone, PhoneError
from ninjatap.elements import ElementList
from ninjatap.trajectory import tap


def once(phone: Phone, elements: ElementList, element_id: int) -> bytes:
    """Tap the center of ``element_id`` and return the screenshot taken after it."""
    x, y = elements.center(element_id)
    display = phone.display()
    status = phone.inject(tap(x, y, size=display.size), rotation=display.rotation)
    if status != "ok":
        raise PhoneError(status)
    return phone.screencap()
