"""Deterministic chemical/ionic reaction conservation verification (atom & charge balance).

Uses a strict context-free lexer for chemical formulas (brackets, hydrates, ionic charges)
and `sympy.Matrix.nullspace()` for exact integer stoichiometric balancing.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from fractions import Fraction
from typing import Any

_VALID_ELEMENTS = frozenset(
    {
        "H", "He", "Li", "Be", "B", "C", "N", "O", "F", "Ne",
        "Na", "Mg", "Al", "Si", "P", "S", "Cl", "Ar", "K", "Ca",
        "Sc", "Ti", "V", "Cr", "Mn", "Fe", "Co", "Ni", "Cu", "Zn",
        "Ga", "Ge", "As", "Se", "Br", "Kr", "Rb", "Sr", "Y", "Zr",
        "Nb", "Mo", "Tc", "Ru", "Rh", "Pd", "Ag", "Cd", "In", "Sn",
        "Sb", "Te", "I", "Xe", "Cs", "Ba", "La", "Ce", "Pr", "Nd",
        "Pm", "Sm", "Eu", "Gd", "Tb", "Dy", "Ho", "Er", "Tm", "Yb",
        "Lu", "Hf", "Ta", "W", "Re", "Os", "Ir", "Pt", "Au", "Hg",
        "Tl", "Pb", "Bi", "Po", "At", "Rn", "Fr", "Ra", "Ac", "Th",
        "Pa", "U",
    }
)
_ARROW_PATTERN = re.compile(r"\s*(?:===|==|->|=>|⇌|<=>|=)\s*")
_STATE_SUFFIX = re.compile(r"(?:\((?:s|l|g|aq)\)|↑|↓)\s*$")


def _parse_segment_atoms(formula: str) -> Counter[str]:
    if not formula:
        raise ValueError("empty_formula_segment")
    stack: list[tuple[Counter[str], str]] = [(Counter(), "")]
    i = 0
    n = len(formula)
    while i < n:
        ch = formula[i]
        if ch in "([":
            stack.append((Counter(), ch))
            i += 1
        elif ch in ")]":
            if len(stack) <= 1:
                raise ValueError("unmatched_closing_bracket")
            group_counts, opener = stack.pop()
            if (opener == "(" and ch != ")") or (opener == "[" and ch != "]"):
                raise ValueError("mismatched_bracket_pair")
            i += 1
            num_start = i
            while i < n and formula[i].isdigit():
                i += 1
            mult = int(formula[num_start:i]) if i > num_start else 1
            if mult <= 0 or mult > 200:
                raise ValueError("invalid_stoichiometric_subscript")
            for elem, cnt in group_counts.items():
                stack[-1][0][elem] += cnt * mult
        elif ch.isupper():
            elem_start = i
            i += 1
            while i < n and formula[i].islower():
                i += 1
            elem = formula[elem_start:i]
            if elem not in _VALID_ELEMENTS:
                raise ValueError(f"unknown_chemical_element:{elem}")
            num_start = i
            while i < n and formula[i].isdigit():
                i += 1
            mult = int(formula[num_start:i]) if i > num_start else 1
            if mult <= 0 or mult > 200:
                raise ValueError("invalid_stoichiometric_subscript")
            stack[-1][0][elem] += mult
        else:
            raise ValueError(f"unexpected_formula_char:{ch}")
    if len(stack) != 1:
        raise ValueError("unclosed_bracket_in_formula")
    if not stack[0][0]:
        raise ValueError("no_atoms_parsed")
    return stack[0][0]


def parse_chemical_term(raw_term: str) -> tuple[Fraction, Counter[str], int]:
    """Return (stoichiometric_coeff, element_counts, ionic_charge)."""
    text = _STATE_SUFFIX.sub("", raw_term.strip())
    if not text or len(text) > 120:
        raise ValueError("invalid_chemical_term")

    # Leading stoichiometric coefficient (integer or simple fraction like 3/2)
    coeff_match = re.match(r"^(\d+(?:/\d+)?)\s*(.*)$", text)
    coeff = Fraction(1)
    if coeff_match and coeff_match.group(2):
        coeff = Fraction(coeff_match.group(1))
        if coeff <= 0 or coeff > 500 or coeff.denominator > 100:
            raise ValueError("invalid_coefficient")
        text = coeff_match.group(2).strip()

    # Pure electron term e^- or e-
    if text in {"e^-", "e-", "e^{-}"}:
        return coeff, Counter(), -1

    # Extract trailing charge: e.g. ^2-, ^3+, ^+, ^-, ^{2-}, or bare Cr3+ is NOT guessed unless ^ or single +/-
    charge = 0
    caret_match = re.search(r"\^\{?(\d*)([+-])([0-9]*)\}?$", text)
    if caret_match:
        d1, sign, d2 = caret_match.groups()
        mag_str = d1 or d2 or "1"
        if d1 and d2:
            raise ValueError("ambiguous_charge_notation")
        mag = int(mag_str)
        if mag > 20:
            raise ValueError("charge_limit")
        charge = mag if sign == "+" else -mag
        text = text[: caret_match.start()].strip()
    elif text.endswith("+") or text.endswith("-"):
        sign = text[-1]
        text = text[:-1].strip()
        charge = 1 if sign == "+" else -1

    # Handle hydrate dot notation: CuSO4·5H2O or CuSO4*5H2O
    parts = re.split(r"[·•*]", text)
    total_atoms: Counter[str] = Counter()
    for part in parts:
        part = part.strip()
        if not part:
            raise ValueError("empty_hydrate_part")
        m_sub = re.match(r"^(\d+)\s*(.+)$", part)
        part_mult = 1
        if m_sub:
            part_mult = int(m_sub.group(1))
            if part_mult <= 0 or part_mult > 100:
                raise ValueError("invalid_hydrate_multiplier")
            part = m_sub.group(2).strip()
        seg_atoms = _parse_segment_atoms(part)
        for elem, cnt in seg_atoms.items():
            total_atoms[elem] += cnt * part_mult

    return coeff, total_atoms, charge


def _split_species(side: str) -> list[str]:
    """Split reactants or products on '+' that are NOT part of an ionic charge."""
    tokens: list[str] = []
    cur: list[str] = []
    i = 0
    n = len(side)
    brace_depth = 0
    while i < n:
        ch = side[i]
        if ch == "{":
            brace_depth += 1
            cur.append(ch)
            i += 1
            continue
        if ch == "}":
            brace_depth = max(0, brace_depth - 1)
            cur.append(ch)
            i += 1
            continue
        if ch == "+" and brace_depth == 0:
            prev_nonspace = "".join(cur).rstrip()
            # '+' belongs to charge if preceded by '^' or '^<digits>', OR if followed by arrow/end/another '+'
            rest = side[i + 1 :].lstrip()
            is_caret_charge = bool(re.search(r"\^\d*$", prev_nonspace))
            is_trailing_single_plus = (
                not is_caret_charge
                and bool(prev_nonspace)
                and (not rest or rest.startswith("+"))
            )
            if is_caret_charge or is_trailing_single_plus:
                cur.append(ch)
                i += 1
                continue
            tokens.append("".join(cur).strip())
            cur = []
            i += 1
            continue
        cur.append(ch)
        i += 1
    if cur:
        tokens.append("".join(cur).strip())
    if not tokens or any(not tok for tok in tokens):
        raise ValueError("empty_reaction_species")
    return tokens


def check_reaction_operation(s, args: dict[str, Any]) -> dict[str, Any]:
    raw_eq = args.get("equation")
    if not isinstance(raw_eq, str) or not 0 < len(raw_eq) <= 512:
        raise ValueError("invalid_reaction_equation")

    sides = _ARROW_PATTERN.split(raw_eq.strip())
    if len(sides) != 2:
        raise ValueError("reaction_requires_single_arrow")
    left_terms = _split_species(sides[0])
    right_terms = _split_species(sides[1])
    if len(left_terms) + len(right_terms) > 20:
        raise ValueError("too_many_species")

    reactants = [parse_chemical_term(t) for t in left_terms]
    products = [parse_chemical_term(t) for t in right_terms]

    all_elements = sorted(
        {elem for _, atoms, _ in (*reactants, *products) for elem in atoms}
    )
    if not all_elements:
        raise ValueError("no_elements_in_reaction")

    atom_deltas: dict[str, str] = {}
    for elem in all_elements:
        lhs_count = sum((coeff * atoms[elem] for coeff, atoms, _ in reactants), Fraction(0))
        rhs_count = sum((coeff * atoms[elem] for coeff, atoms, _ in products), Fraction(0))
        diff = lhs_count - rhs_count
        if diff != 0:
            atom_deltas[elem] = f"{lhs_count} -> {rhs_count}"

    lhs_charge = sum((coeff * chg for coeff, _, chg in reactants), Fraction(0))
    rhs_charge = sum((coeff * chg for coeff, _, chg in products), Fraction(0))
    charge_conserved = lhs_charge == rhs_charge
    atom_conserved = len(atom_deltas) == 0
    balanced = atom_conserved and charge_conserved

    # Compute canonical minimal integer stoichiometric vector if uniquely balanceable
    species_list = [*reactants, *products]
    num_reactants = len(reactants)
    rows = []
    for elem in all_elements:
        row = [
            atoms[elem] if idx < num_reactants else -atoms[elem]
            for idx, (_, atoms, _) in enumerate(species_list)
        ]
        rows.append(row)
    if any(chg != 0 for _, _, chg in species_list):
        rows.append(
            [
                chg if idx < num_reactants else -chg
                for idx, (_, _, chg) in enumerate(species_list)
            ]
        )
    mat = s.Matrix(rows)
    null_basis = mat.nullspace()

    payload: dict[str, Any] = {
        "balanced": balanced,
        "atom_conserved": atom_conserved,
        "charge_conserved": charge_conserved,
        "left_charge": str(lhs_charge),
        "right_charge": str(rhs_charge),
        "atom_imbalances": atom_deltas,
        "nullspace_dimension": len(null_basis),
    }
    if len(null_basis) == 1:
        vec = null_basis[0]
        lcm_denom = 1
        for val in vec:
            r = s.Rational(val)
            lcm_denom = int(s.ilcm(lcm_denom, r.q))
        int_vec = [int(s.Rational(val) * lcm_denom) for val in vec]
        if all(v < 0 for v in int_vec):
            int_vec = [-v for v in int_vec]
        if all(v > 0 for v in int_vec):
            gcd_all = int_vec[0]
            for v in int_vec[1:]:
                gcd_all = int(s.igcd(gcd_all, v))
            payload["minimal_coefficients"] = [v // gcd_all for v in int_vec]

    return {
        "engine_version": "chem-balance-v1",
        "status": "ok",
        "result": json.dumps(payload, ensure_ascii=False),
        "conditions": [],
        "checked_scope": "equivalence",
        "verdict": "equal" if balanced else "not_equal",
    }
