"""Hartree-based conversion, CODATA 2022 and thermochemical calorie convention.

Source: https://physics.nist.gov/cuu/Constants/Table/allascii.txt
Calorie: https://www.nist.gov/pml/special-publication-811/nist-guide-si-footnotes
"""
from decimal import Decimal, localcontext
from types import MappingProxyType

from .models import Unit, finite_number

CONSTANTS_VERSION = "codata_2022_thermochemical_calorie_v1"
HARTREE_JOULE = Decimal("4.3597447222060e-18")
AVOGADRO_PER_MOL = Decimal("6.02214076e23")
KCAL_JOULE = Decimal("4184")
with localcontext() as context:
    context.prec = 40
    HARTREE_TO_KJ_DECIMAL = HARTREE_JOULE * AVOGADRO_PER_MOL / Decimal("1000")
    HARTREE_TO_KCAL_DECIMAL = HARTREE_JOULE * AVOGADRO_PER_MOL / KCAL_JOULE
HARTREE_TO_KJ = float(HARTREE_TO_KJ_DECIMAL)
HARTREE_TO_KCAL = float(HARTREE_TO_KCAL_DECIMAL)
FACTORS = MappingProxyType({Unit.HARTREE: 1.0, Unit.KCAL_MOL: HARTREE_TO_KCAL, Unit.KJ_MOL: HARTREE_TO_KJ})
UNIT_LABELS = MappingProxyType({Unit.HARTREE: "Hartree", Unit.KCAL_MOL: "kcal/mol", Unit.KJ_MOL: "kJ/mol"})


def from_hartree(value: float, unit: Unit | str) -> float:
    return finite_number(finite_number(value) * FACTORS[Unit(unit)])


def to_hartree(value: float, unit: Unit | str) -> float:
    return finite_number(finite_number(value) / FACTORS[Unit(unit)])


def convert_energy(value: float, source_unit: Unit | str, target_unit: Unit | str) -> float:
    number = finite_number(value)
    source, target = Unit(source_unit), Unit(target_unit)
    if source == target:
        return number
    return finite_number(number * (FACTORS[target] / FACTORS[source]))
