"""Komunikaty statusu mówione przez NVDA. Bez NVDA program jest po prostu cichy."""

_output = None


def speak(text):
    global _output
    try:
        if _output is None:
            from accessible_output2.outputs.nvda import NVDA

            _output = NVDA()
        if _output.is_active():
            _output.speak(text)
    except (ImportError, OSError, AttributeError):
        pass
