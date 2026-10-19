import pytest

from gaussianreadpro.core.elements import element_symbol


@pytest.mark.parametrize(("number", "symbol"), [
    (1, "H"), (5, "B"), (6, "C"), (17, "Cl"), (26, "Fe"), (53, "I"),
    (118, "Og"),
])
def test_element_symbol_known_elements(number, symbol):
    assert element_symbol(number) == symbol


@pytest.mark.parametrize("number", [0, 119, -1, True, 1.0, "6"])
def test_element_symbol_marks_invalid_atomic_number_unknown(number):
    assert element_symbol(number) == "?"


def test_element_symbol_covers_all_atomic_numbers():
    symbols = [element_symbol(number) for number in range(1, 119)]
    assert len(symbols) == 118
    assert all(symbol != "?" for symbol in symbols)
    assert len(set(symbols)) == 118
