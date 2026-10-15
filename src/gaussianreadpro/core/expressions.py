"""Bounded expression DSL. No Python evaluation, calls, attributes or node references."""
from __future__ import annotations

import difflib
import json
import operator
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from types import MappingProxyType

from .models import (CombinationMode, CompileResult, Diagnostic, EnergyDependency, EnergyKind,
                     EnergyRef, ExpressionDocument, ExpressionPurpose, ExpressionResult,
                     KindPolicy, SCFConvergence, Severity, SourceFile, Termination,
                     finite_number, snapshot_to_dict)
from .parser import select_job
from .units import to_hartree

MAX_TEXT = 8192
MAX_NODES = 256
MAX_DEPTH = 32
NUMBER = re.compile(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eEdD][+-]?[0-9]+)?")
OPS = {"add": operator.add, "sub": operator.sub, "mul": operator.mul, "div": operator.truediv}
UNITS = {"hartree": "hartree", "kcal/mol": "kcal_mol", "kj/mol": "kj_mol",
         "kcal_mol": "kcal_mol", "kj_mol": "kj_mol"}


class ExpressionError(ValueError):
    def __init__(self, code, *, node=None, start=None, end=None, **params):
        if node is not None and isinstance(node, Mapping) and "span" in node:
            start, end = node["span"]
        if start is not None:
            params.update(start=start, end=end if end is not None else start + 1)
        self.diagnostic = Diagnostic(code, Severity.ERROR, params)
        super().__init__(code)


def unique_diagnostics(items):
    result, seen = [], set()
    for diagnostic in items:
        key = json.dumps(snapshot_to_dict(diagnostic), sort_keys=True, allow_nan=False)
        if key not in seen:
            result.append(diagnostic)
            seen.add(key)
    return tuple(result)


def ref_ast(ref: EnergyRef):
    tree = {"type": "ref", "source_file_id": ref.source_file_id,
            "job_id": ref.job_id, "kind_policy": ref.kind_policy.value}
    if ref.kind is not None:
        tree["kind"] = ref.kind.value
    return tree


def ast_ref(tree):
    return EnergyRef(tree["source_file_id"], tree["job_id"], tree["kind_policy"], tree.get("kind"))


def _ref_token(ref):
    suffix = f"/{ref.kind.value}" if ref.kind_policy == KindPolicy.FIXED else ""
    return f"ref:{ref.source_file_id}/{ref.job_id}{suffix}"


@dataclass(frozen=True)
class AliasIndex:
    bindings: Mapping[str, EnergyRef] = field(default_factory=dict)

    def __post_init__(self):
        copied = dict(self.bindings)
        for alias, ref in copied.items():
            if (not isinstance(alias, str) or not alias.strip() or alias != alias.strip()
                    or any(c in alias for c in "{}\r\n") or alias.startswith("ref:") or len(alias) > 1024):
                raise ValueError("Alias is empty, reserved or cannot be represented by a reference token")
            if not isinstance(ref, EnergyRef):
                raise TypeError("Aliases must bind EnergyRef objects")
        object.__setattr__(self, "bindings", MappingProxyType(copied))

    @classmethod
    def from_pairs(cls, pairs):
        result = {}
        for alias, ref in pairs:
            if alias in result:
                raise ValueError(f"Duplicate alias: {alias}")
            result[alias] = ref
        return cls(result)

    @classmethod
    def with_unique_labels(cls, pairs):
        result = {}
        for index, (label, ref) in enumerate(pairs, 1):
            root = str(label).strip()
            if (not root or any(c in root for c in "{}\r\n") or root.startswith("ref:") or len(root) > 1000):
                root = f"species_{index}"
            alias, suffix = root, 2
            while alias in result:
                alias = f"{root} ({suffix})"
                suffix += 1
            result[alias] = ref
        return cls(result)

    def resolve(self, alias):
        if alias.startswith("ref:"):
            parts = alias[4:].split("/")
            try:
                if len(parts) == 2:
                    return EnergyRef(*parts)
                if len(parts) == 3:
                    return EnergyRef(parts[0], parts[1], KindPolicy.FIXED, parts[2])
            except (ValueError, TypeError):
                pass
            raise ExpressionError("invalid_reference_token", alias=alias)
        if alias not in self.bindings:
            raise ExpressionError("unknown_alias", alias=alias,
                                  suggestions=difflib.get_close_matches(alias, self.bindings, n=5))
        return self.bindings[alias]

    def label_for(self, ref):
        return next((alias for alias, bound in self.bindings.items() if bound == ref), _ref_token(ref))

    def renamed(self, old, new):
        if old not in self.bindings or (new != old and new in self.bindings):
            raise ValueError("Unknown old alias or duplicate new alias")
        return AliasIndex({new if key == old else key: ref for key, ref in self.bindings.items()})

    def suggest(self, prefix, limit=8):
        return tuple(key for key in self.bindings if key.casefold().startswith(prefix.casefold()))[:limit]


@dataclass(frozen=True)
class _Token:
    kind: str
    text: str
    start: int
    end: int


def _tokens(text):
    result, pos = [], 0
    while pos < len(text):
        if text[pos].isspace():
            pos += 1
            continue
        start = pos
        if text.startswith("@{", pos):
            end = text.find("}", pos + 2)
            if end < 0:
                raise ExpressionError("unclosed_reference", start=pos, end=len(text))
            result.append(_Token("ref", text[pos + 2:end], pos, end + 1))
            pos = end + 1
        elif text[pos] == "[":
            end = text.find("]", pos + 1)
            if end < 0:
                raise ExpressionError("unclosed_unit", start=pos, end=len(text))
            result.append(_Token("unit", text[pos + 1:end], pos, end + 1))
            pos = end + 1
        elif match := NUMBER.match(text, pos):
            pos = match.end()
            result.append(_Token("number", match.group(), start, pos))
        elif text[pos] in "+-*/()":
            pos += 1
            result.append(_Token(text[start], text[start], start, pos))
        else:
            raise ExpressionError("unsupported_syntax", start=pos, end=pos + 1)
        if len(result) > 1024:
            raise ExpressionError("expression_too_complex", start=start)
    return result + [_Token("end", "", len(text), len(text))]


class _Parser:
    def __init__(self, text, aliases):
        self.tokens = _tokens(text)
        self.position = 0
        self.nodes = 0
        self.aliases = aliases

    @property
    def token(self):
        return self.tokens[self.position]

    def advance(self):
        token = self.token
        self.position += 1
        return token

    def node(self, data, start, end):
        self.nodes += 1
        if self.nodes > MAX_NODES:
            raise ExpressionError("expression_too_complex", start=start, end=end)
        return {**data, "span": [start, end]}

    def expression(self, minimum=0, depth=1):
        if depth > MAX_DEPTH:
            raise ExpressionError("expression_too_deep", start=self.token.start)
        token = self.advance()
        if token.kind in ("+", "-"):
            child = self.expression(30, depth + 1)
            left = self.node({"type": "unary", "op": "pos" if token.kind == "+" else "neg",
                              "operand": child}, token.start, child["span"][1])
        elif token.kind == "(":
            left = self.expression(0, depth + 1)
            if self.token.kind != ")":
                raise ExpressionError("missing_closing_parenthesis", start=self.token.start)
            self.advance()
        elif token.kind == "ref":
            try:
                ref = self.aliases.resolve(token.text)
            except ExpressionError as exc:
                raise ExpressionError(exc.diagnostic.code, start=token.start, end=token.end,
                                      **dict(exc.diagnostic.params)) from exc
            left = self.node(ref_ast(ref), token.start, token.end)
        elif token.kind == "number":
            try:
                number = finite_number(float(token.text.replace("D", "E").replace("d", "e")))
            except ValueError as exc:
                raise ExpressionError("number_not_finite", start=token.start, end=token.end) from exc
            if self.token.kind == "unit":
                unit = self.advance()
                value = UNITS.get(unit.text.strip().lower())
                if value is None:
                    raise ExpressionError("unknown_unit", start=unit.start, end=unit.end, unit=unit.text)
                left = self.node({"type": "energy_constant", "value": number, "unit": value}, token.start, unit.end)
            else:
                left = self.node({"type": "scalar", "value": number}, token.start, token.end)
        else:
            raise ExpressionError("expected_operand", start=token.start, end=token.end)
        precedence = {"+": 10, "-": 10, "*": 20, "/": 20}
        while self.token.kind in precedence and precedence[self.token.kind] >= minimum:
            op = self.advance()
            right = self.expression(precedence[op.kind] + 1, depth + 1)
            left = self.node({"type": "binary", "op": {"+": "add", "-": "sub", "*": "mul", "/": "div"}[op.kind],
                              "left": left, "right": right}, left["span"][0], right["span"][1])
        return left


@dataclass(frozen=True)
class _Info:
    dimension: str
    value: float | None


def _walk(root, resolver=None):
    stack, count, infos = [(root, 1, False)], 0, {}
    while stack:
        node, depth, visited = stack.pop()
        if not isinstance(node, Mapping):
            raise ExpressionError("invalid_expression_tree")
        kind = node.get("type")
        if not visited:
            count += 1
            if count > MAX_NODES:
                raise ExpressionError("expression_too_complex")
            if depth > MAX_DEPTH:
                raise ExpressionError("expression_too_deep")
            keys = {"ref": {"type", "source_file_id", "job_id", "kind_policy"},
                    "scalar": {"type", "value"}, "energy_constant": {"type", "value", "unit"},
                    "unary": {"type", "op", "operand"}, "binary": {"type", "op", "left", "right"}}
            if not isinstance(kind, str) or kind not in keys:
                raise ExpressionError("invalid_expression_tree")
            required = keys[kind]
            allowed = required | {"span"} | ({"kind"} if kind == "ref" else set())
            if not required <= node.keys() or not node.keys() <= allowed:
                raise ExpressionError("invalid_expression_tree")
            span = node.get("span")
            if span is not None and (not isinstance(span, (tuple, list)) or len(span) != 2
                                     or any(isinstance(n, bool) or not isinstance(n, int) for n in span)
                                     or not 0 <= span[0] <= span[1] <= MAX_TEXT):
                raise ExpressionError("invalid_expression_span")
            stack.append((node, depth, True))
            if kind == "unary":
                stack.append((node["operand"], depth + 1, False))
            elif kind == "binary":
                stack.extend([(node["right"], depth + 1, False), (node["left"], depth + 1, False)])
            continue
        try:
            if kind == "ref":
                ref = ast_ref(node)
                if node["source_file_id"] != ref.source_file_id or node["job_id"] != ref.job_id:
                    raise ExpressionError("noncanonical_reference_uuid", node=node)
                info = _Info("energy", resolver(ref) if resolver else None)
            elif kind in ("scalar", "energy_constant"):
                number = finite_number(node["value"])
                info = _Info("scalar" if kind == "scalar" else "energy",
                             number if kind == "scalar" else to_hartree(number, node["unit"]))
            elif kind == "unary":
                if node["op"] not in {"pos", "neg"}:
                    raise ExpressionError("unsupported_operator", node=node)
                operand = infos[id(node["operand"])]
                info = _Info(operand.dimension, None if operand.value is None else
                             finite_number(operand.value * (-1 if node["op"] == "neg" else 1)))
            else:
                left, right = infos[id(node["left"])], infos[id(node["right"])]
                op = node["op"]
                if op not in OPS:
                    raise ExpressionError("unsupported_operator", node=node)
                if op in {"add", "sub"}:
                    if left.dimension != right.dimension:
                        raise ExpressionError("dimension_mismatch", node=node)
                    dimension = left.dimension
                elif op == "mul":
                    if left.dimension == right.dimension == "energy":
                        raise ExpressionError("energy_multiplication_forbidden", node=node)
                    dimension = "energy" if "energy" in (left.dimension, right.dimension) else "scalar"
                else:
                    if right.dimension != "scalar":
                        raise ExpressionError("energy_divisor_forbidden", node=node)
                    if right.value == 0:
                        raise ExpressionError("division_by_zero", node=node)
                    dimension = left.dimension
                value = (None if left.value is None or right.value is None
                         else finite_number(OPS[op](left.value, right.value)))
                info = _Info(dimension, value)
        except (ValueError, TypeError, OverflowError, ZeroDivisionError) as exc:
            if isinstance(exc, ExpressionError):
                raise
            raise ExpressionError("invalid_value_or_arithmetic", node=node) from exc
        infos[id(node)] = info
    result = infos[id(root)]
    if result.dimension != "energy":
        raise ExpressionError("energy_expression_required", node=root)
    return result.value


def validate_ast(tree):
    _walk(tree)


def compile_expression(text, aliases=None, *, purpose=ExpressionPurpose.SYSTEM,
                       combination_mode=CombinationMode.STANDARD):
    aliases = aliases if isinstance(aliases, AliasIndex) else AliasIndex(aliases or {})
    purpose, combination_mode = ExpressionPurpose(purpose), CombinationMode(combination_mode)
    try:
        if not isinstance(text, str) or not text.strip():
            raise ExpressionError("empty_expression", start=0, end=0)
        if len(text) > MAX_TEXT:
            raise ExpressionError("expression_too_long", start=MAX_TEXT, end=len(text))
        parser = _Parser(text, aliases)
        tree = parser.expression()
        if parser.token.kind != "end":
            raise ExpressionError("unexpected_token", start=parser.token.start, end=parser.token.end)
        validate_ast(tree)
        return CompileResult(ExpressionDocument(tree, text, purpose=purpose, combination_mode=combination_mode))
    except ExpressionError as exc:
        return CompileResult(None, (exc.diagnostic,))


def edit_expression(current, text, aliases=None, *, purpose=None, combination_mode=None):
    result = compile_expression(text, aliases,
                                purpose=purpose or (current.purpose if current else ExpressionPurpose.SYSTEM),
                                combination_mode=combination_mode or (current.combination_mode if current else CombinationMode.STANDARD))
    if result.valid:
        return result.expression
    return ExpressionDocument(current.ast if current else None, current.display_text if current else "",
                              purpose=purpose or (current.purpose if current else ExpressionPurpose.SYSTEM),
                              combination_mode=combination_mode or (current.combination_mode if current else CombinationMode.STANDARD),
                              draft_text=text, draft_error=result.diagnostics[0])


def expression_references(expression):
    if expression.ast is None:
        return ()
    result, stack = [], [expression.ast]
    while stack:
        node = stack.pop()
        if node["type"] == "ref":
            ref = ast_ref(node)
            if ref not in result:
                result.append(ref)
        elif node["type"] == "unary":
            stack.append(node["operand"])
        elif node["type"] == "binary":
            stack.extend([node["right"], node["left"]])
    return tuple(result)


def draft_references(expression, aliases):
    """Recognize complete reference tokens in unfinished text without evaluating it."""
    aliases = aliases if isinstance(aliases, AliasIndex) else AliasIndex(aliases)
    found = []
    for token in re.finditer(r"@\{([^{}\r\n]*)\}", expression.draft_text or ""):
        try:
            ref = aliases.resolve(token.group(1))
        except ExpressionError:
            continue
        if ref not in found:
            found.append(ref)
    return tuple(found)


def render_expression(expression, aliases=None):
    aliases = aliases if isinstance(aliases, AliasIndex) else AliasIndex(aliases or {})
    if expression.ast is None:
        return expression.draft_text or ""
    def render(node):
        kind = node["type"]
        if kind == "ref":
            return "@{" + aliases.label_for(ast_ref(node)) + "}"
        if kind == "scalar":
            return repr(node["value"])
        if kind == "energy_constant":
            return f"{node['value']!r}[{node['unit']}]"
        if kind == "unary":
            return ("-" if node["op"] == "neg" else "+") + "(" + render(node["operand"]) + ")"
        symbol = {"add": "+", "sub": "-", "mul": "*", "div": "/"}[node["op"]]
        return f"({render(node['left'])} {symbol} {render(node['right'])})"
    return render(expression.ast)


def expression_from_ast(tree, aliases=None, *, purpose=ExpressionPurpose.SYSTEM,
                        combination_mode=CombinationMode.STANDARD):
    document = ExpressionDocument(tree, "", purpose=purpose, combination_mode=combination_mode)
    def clean(node):
        result = {key: value for key, value in node.items() if key != "span"}
        if node["type"] == "binary":
            result.update(left=clean(node["left"]), right=clean(node["right"]))
        elif node["type"] == "unary":
            result["operand"] = clean(node["operand"])
        return result
    return replace(document, ast=clean(document.ast), display_text=render_expression(document, aliases))


def components_expression(components, *, offset=0.0, offset_unit="hartree", aliases=None,
                          purpose=ExpressionPurpose.SYSTEM):
    tree = None
    for index, (ref, coefficient) in enumerate(components):
        if index >= MAX_NODES:
            raise ValueError("Too many expression components")
        coefficient = finite_number(coefficient)
        term = ref_ast(ref) if coefficient == 1 else {"type": "binary", "op": "mul",
                "left": {"type": "scalar", "value": coefficient}, "right": ref_ast(ref)}
        tree = term if tree is None else {"type": "binary", "op": "add", "left": tree, "right": term}
    offset = finite_number(offset)
    if offset or tree is None:
        term = {"type": "energy_constant", "value": offset, "unit": offset_unit}
        tree = term if tree is None else {"type": "binary", "op": "add", "left": tree, "right": term}
    return expression_from_ast(tree, aliases, purpose=purpose)


def composite_gibbs_expression(high_scf, low_gibbs, low_scf, aliases=None):
    if any(ref.kind_policy != KindPolicy.FIXED for ref in (high_scf, low_gibbs, low_scf)):
        raise ValueError("Composite template requires explicit fixed energy kinds")
    if (high_scf.kind != EnergyKind.SCF or low_gibbs.kind != EnergyKind.GIBBS_TOTAL
            or low_scf.kind != EnergyKind.SCF
            or (low_gibbs.source_file_id, low_gibbs.job_id) != (low_scf.source_file_id, low_scf.job_id)):
        raise ValueError("Low-level Gibbs and SCF must belong to the same job")
    tree = {"type": "binary", "op": "add", "left": ref_ast(high_scf),
            "right": {"type": "binary", "op": "sub", "left": ref_ast(low_gibbs), "right": ref_ast(low_scf)}}
    return expression_from_ast(tree, aliases, combination_mode=CombinationMode.COMPOSITE_GIBBS)


@dataclass(frozen=True)
class EnergyContext:
    sources: Mapping[str, SourceFile]
    energy_kind: EnergyKind = EnergyKind.GIBBS_TOTAL
    allow_abnormal_jobs: bool = False

    def __post_init__(self):
        sources = dict(self.sources)
        if type(self.allow_abnormal_jobs) is not bool:
            raise TypeError("Abnormal-job opt-in must be an explicit bool")
        if any(key != source.id for key, source in sources.items()):
            raise ValueError("Source index keys must be file UUIDs")
        object.__setattr__(self, "sources", MappingProxyType(sources))
        object.__setattr__(self, "energy_kind", EnergyKind(self.energy_kind))


def evaluate_expression(expression, context):
    if expression.draft_error is not None or expression.ast is None:
        diagnostic = Diagnostic("expression_has_invalid_draft", Severity.ERROR)
        return ExpressionResult(None, (), (diagnostic,) + ((expression.draft_error,) if expression.draft_error else ()))
    dependencies, diagnostics, kinds, cache = {}, [], set(), {}
    def resolve(ref):
        if ref in cache:
            return cache[ref]
        kind = ref.kind if ref.kind_policy == KindPolicy.FIXED else context.energy_kind
        kinds.add(kind)
        source = context.sources.get(ref.source_file_id)
        if source is None:
            diagnostics.append(Diagnostic("source_not_found", Severity.ERROR, {"source_file_id": ref.source_file_id}))
            cache[ref] = None
            return None
        selected = select_job(source, kind, job_id=ref.job_id)
        for diagnostic in selected.diagnostics:
            severity = diagnostic.severity
            if diagnostic.code in {"source_unavailable", "job_not_found", "missing_energy"}:
                severity = Severity.ERROR
            elif diagnostic.code == "scf_convergence_failed" and selected.job and selected.job.scf_convergence == SCFConvergence.CONVERGED:
                severity = Severity.WARNING
            elif diagnostic.params.get("kind") not in (None, kind.value):
                severity = Severity.WARNING
            diagnostics.append(replace(diagnostic, severity=severity,
                                       params={**diagnostic.params, "source_file_id": source.id, "job_id": ref.job_id}))
        if selected.job is not None:
            if selected.job.termination != Termination.NORMAL:
                diagnostics.append(Diagnostic("job_not_normal", Severity.WARNING if context.allow_abnormal_jobs else Severity.ERROR,
                                              {"job_id": ref.job_id, "termination": selected.job.termination.value}))
            if selected.job.scf_convergence == SCFConvergence.FAILED:
                diagnostics.append(Diagnostic("scf_not_converged", Severity.ERROR, {"job_id": ref.job_id}))
        energy = selected.energy
        if energy is not None:
            key = (source.id, energy.job_id, kind)
            dependencies[key] = EnergyDependency(source.id, energy.job_id, kind, energy.source_line,
                                                  energy.value_hartree, source.display_name, source.sha256,
                                                  selected.job.metadata)
        cache[ref] = energy.value_hartree if energy else None
        return cache[ref]
    try:
        value = _walk(expression.ast, resolve)
    except ExpressionError as exc:
        diagnostics.append(exc.diagnostic)
        value = None
    if expression.combination_mode == CombinationMode.STANDARD:
        if kinds and kinds != {context.energy_kind}:
            diagnostics.append(Diagnostic("energy_kind_mismatch", Severity.ERROR,
                                          {"expected": context.energy_kind.value, "actual": sorted(k.value for k in kinds)}))
    else:
        if context.energy_kind != EnergyKind.GIBBS_TOTAL or kinds != {EnergyKind.SCF, EnergyKind.GIBBS_TOTAL}:
            diagnostics.append(Diagnostic("invalid_composite_gibbs_kinds", Severity.ERROR))
        diagnostics.append(Diagnostic("composite_gibbs_approximation", Severity.WARNING))
    diagnostics = unique_diagnostics(diagnostics)
    if any(d.severity == Severity.ERROR for d in diagnostics):
        value = None
    return ExpressionResult(value, tuple(dependencies.values()), diagnostics)
