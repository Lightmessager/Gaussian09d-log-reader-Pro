import math
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

import pytest

from gaussianreadpro.core.models import EnergyKind, EnergyRef, EnergyValue, KindPolicy, Unit
from gaussianreadpro.core.units import (HARTREE_TO_KCAL_DECIMAL, HARTREE_TO_KJ_DECIMAL,
                                       convert_energy, from_hartree, to_hartree)

ID = "53e06f66-b08d-498b-8476-aae6485a0823"


def test_conversion_from_primary_constants():
    assert HARTREE_TO_KJ_DECIMAL == Decimal("2625.499639479162971656")
    assert math.isclose(float(HARTREE_TO_KCAL_DECIMAL), 627.5094740628975, rel_tol=1e-15)
    assert convert_energy(1, Unit.KCAL_MOL, Unit.KJ_MOL) == pytest.approx(4.184, abs=1e-14)


@pytest.mark.parametrize("value", [0, -0.008, 0.024, -150.123456789])
@pytest.mark.parametrize("unit", list(Unit))
def test_conversion_round_trip_preserves_hartree(value, unit):
    assert to_hartree(from_hartree(value, unit), unit) == pytest.approx(value, rel=1e-14, abs=1e-15)
    assert convert_energy(value, Unit.HARTREE, Unit.HARTREE) == value


@pytest.mark.parametrize("invalid", [True, False, float("nan"), float("inf"), -float("inf"), "1"])
def test_nonfinite_or_non_numeric_values_rejected(invalid):
    with pytest.raises((ValueError, TypeError)):
        from_hartree(invalid, Unit.KCAL_MOL)
    with pytest.raises((ValueError, TypeError)):
        EnergyValue(EnergyKind.SCF, invalid, "raw", 1, ID)


def test_conversion_overflow_and_unknown_unit_rejected():
    with pytest.raises(ValueError):
        from_hartree(1e308, Unit.KJ_MOL)
    with pytest.raises(ValueError):
        from_hartree(1, "eV")
    with pytest.raises(ValueError):
        from_hartree(10 ** 1000, Unit.HARTREE)
    with pytest.raises(ValueError):
        EnergyValue(EnergyKind.SCF, -1, "-1", True, ID)


def test_energy_reference_policy_validates_identity_and_kind():
    ref = EnergyRef(ID.upper(), ID, KindPolicy.FIXED, EnergyKind.GIBBS_TOTAL)
    assert ref.source_file_id == ID
    with pytest.raises(ValueError):
        EnergyRef(ID, ID, KindPolicy.FIXED)
    with pytest.raises(ValueError):
        EnergyRef(ID, ID, KindPolicy.FOLLOW_PATH, EnergyKind.SCF)
    with pytest.raises(ValueError):
        EnergyRef("file-name", ID)


def test_core_imports_without_site_packages_or_ui():
    root = Path(__file__).resolve().parents[1]
    code = ("import sys; sys.path.insert(0, 'src'); "
            "from gaussianreadpro.core import parse_log, from_hartree, compile_expression, calculate_path; "
            "assert not any(x in sys.modules for x in ('PySide6','plotly','tkinter','numpy')); "
            "assert from_hartree(0,'kcal_mol') == 0")
    subprocess.run([sys.executable, "-S", "-c", code], cwd=root, check=True, timeout=10)
