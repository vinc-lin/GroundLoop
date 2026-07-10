from groundloop.core.types import Signals, Ticket
from groundloop.domains.android_ivi.component_signals import (
    COMPONENT_MARK, ComponentExtractor, component_of, strip_component)


class _Base:
    def extract(self, logs, ticket):
        return Signals(classes=("Foo",), errors=("NullPointerException",))


def test_extractor_appends_component_marker():
    sig = ComponentExtractor(_Base()).extract((), Ticket("t", "s", "d", component="CarPlay"))
    assert component_of(sig) == "CarPlay"
    assert "NullPointerException" in sig.errors            # base tokens preserved
    assert sig.classes == ("Foo",)


def test_strip_component_removes_marker_only():
    sig = ComponentExtractor(_Base()).extract((), Ticket("t", "s", "d", component="Audio"))
    stripped = strip_component(sig)
    assert component_of(stripped) == "" and "NullPointerException" in stripped.errors
    assert not any(e.startswith(COMPONENT_MARK) for e in stripped.errors)


def test_empty_component_is_noop():
    sig = ComponentExtractor(_Base()).extract((), Ticket("t", "s", "d", component=""))
    assert component_of(sig) == "" and sig.errors == ("NullPointerException",)
