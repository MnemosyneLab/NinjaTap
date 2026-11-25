"""Element list. A model may only name an id that is in the list."""

from dataclasses import dataclass
from typing import Literal


class UnknownElement(Exception):
    def __init__(self, element_id: int):
        super().__init__(f"unknown element {element_id}")
        self.element_id = element_id


@dataclass(frozen=True)
class Element:
    id: int
    kind: Literal["text", "icon"]
    cx: int
    cy: int
    text: str | None = None


class ElementList:
    def __init__(self, elements: list[Element]):
        self.elements = list(elements)
        self._by_id = {element.id: element for element in self.elements}

    def center(self, element_id: int) -> tuple[int, int]:
        try:
            element = self._by_id[element_id]
        except KeyError:
            raise UnknownElement(element_id) from None
        return element.cx, element.cy
