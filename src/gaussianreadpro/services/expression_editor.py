"""Lossless recognition of the simple component form; no energy evaluation."""
from ..core.expressions import ast_ref


def component_form(document):
    """Return ordered (reference, coefficient), offset and unit, or None.

    Deliberately reject algebra that needs distribution or combined constants.
    Expert expressions remain untouched unless a user explicitly replaces them.
    """
    if document is None or document.ast is None or document.draft_error or document.combination_mode != "standard":
        return None
    terms, offsets = [], []

    def visit(tree, sign=1.):
        kind = tree["type"]
        if kind == "ref":
            terms.append((ast_ref(tree), sign))
        elif kind == "unary":
            visit(tree["operand"], sign * (-1 if tree["op"] == "neg" else 1))
        elif kind == "energy_constant":
            offsets.append((sign * tree["value"], tree["unit"]))
        elif kind == "binary" and tree["op"] in ("add", "sub"):
            visit(tree["left"], sign)
            visit(tree["right"], sign * (-1 if tree["op"] == "sub" else 1))
        elif kind == "binary" and tree["op"] == "mul":
            left, right = tree["left"], tree["right"]
            if left["type"] == "ref" and right["type"] == "scalar":
                left, right = right, left
            if left["type"] != "scalar" or right["type"] != "ref":
                raise ValueError
            terms.append((ast_ref(right), sign * left["value"]))
        else:
            raise ValueError

    try:
        visit(document.ast)
        if len(offsets) > 1:
            return None
        offset, unit = offsets[0] if offsets else (0., "hartree")
        return terms, offset, unit
    except ValueError:
        return None
