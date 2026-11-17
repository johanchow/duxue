"""Exact Mendelian & sex-linked genetics probability engine over finite gamete products."""

from __future__ import annotations

import json
import re
from collections import Counter
from fractions import Fraction
from itertools import product
from typing import Any

from math_executor.arithmetic import format_fraction

_SEX_ALLELE_RE = re.compile(r"^(X(?:\^[A-Za-z0-9]+)?|Y)(X(?:\^[A-Za-z0-9]+)?|Y)$")
_AUTOSOMAL_RE = re.compile(r"^([A-Za-z])([A-Za-z])$")


def _parse_locus(genotype: str) -> tuple[str, tuple[str, str]]:
    text = genotype.strip()
    m_sex = _SEX_ALLELE_RE.fullmatch(text)
    if m_sex:
        return "sex", (m_sex.group(1), m_sex.group(2))
    m_auto = _AUTOSOMAL_RE.fullmatch(text)
    if m_auto:
        a1, a2 = m_auto.group(1), m_auto.group(2)
        if a1.lower() != a2.lower():
            raise ValueError(f"mismatched_locus_letters:{text}")
        return f"auto:{a1.lower()}", (a1, a2)
    raise ValueError(f"unsupported_locus_genotype:{text}")


def _canonical_pair(kind: str, a1: str, a2: str) -> str:
    if kind == "sex":
        # Put X before Y; for two X alleles, put uppercase superscript before lowercase
        if a1 == "Y" and a2 != "Y":
            return f"{a2}{a1}"
        if a2 == "Y" and a1 != "Y":
            return f"{a1}{a2}"
        return "".join(sorted((a1, a2)))
    # Autosomal: uppercase allele first (Aa, not aA)
    pair = sorted((a1, a2), key=lambda ch: (0 if ch.isupper() else 1, ch))
    return "".join(pair)


def _locus_phenotype(kind: str, pair_str: str) -> str:
    if kind == "sex":
        m = _SEX_ALLELE_RE.fullmatch(pair_str)
        assert m is not None
        g1, g2 = m.group(1), m.group(2)
        sex = "male" if "Y" in (g1, g2) else "female"
        alleles = [g[2:] for g in (g1, g2) if g.startswith("X^")]
        if not alleles:
            return sex
        dom = any(al[0].isupper() for al in alleles)
        letter = alleles[0][0]
        trait = letter.upper() + "_" if dom else letter.lower() * 2
        return f"{sex}:{trait}"
    # Autosomal complete dominance default (A_ vs aa)
    if pair_str[0].isupper():
        return f"{pair_str[0]}_"
    return pair_str


def genetics_cross_operation(args: dict[str, Any]) -> dict[str, Any]:
    p1_raw = args.get("parent1")
    p2_raw = args.get("parent2")
    lethal_raw = args.get("lethal_genotypes", [])
    if (
        not isinstance(p1_raw, list)
        or not isinstance(p2_raw, list)
        or not 1 <= len(p1_raw) <= 5
        or len(p1_raw) != len(p2_raw)
        or not isinstance(lethal_raw, list)
        or len(lethal_raw) > 20
    ):
        raise ValueError("invalid_genetics_inputs")

    loci1 = [_parse_locus(g) for g in p1_raw]
    loci2 = [_parse_locus(g) for g in p2_raw]
    kinds = [k for k, _ in loci1]
    if kinds != [k for k, _ in loci2] or len(set(kinds)) != len(kinds):
        raise ValueError("parent_loci_mismatch_or_duplicate")

    lethal_patterns = {str(item).strip() for item in lethal_raw if str(item).strip()}

    gametes1 = list(product(*(alleles for _, alleles in loci1)))
    gametes2 = list(product(*(alleles for _, alleles in loci2)))

    geno_counts: Counter[str] = Counter()
    pheno_counts: Counter[str] = Counter()
    total_combinations = len(gametes1) * len(gametes2)
    viable_count = 0

    for g1 in gametes1:
        for g2 in gametes2:
            locus_genos = [
                _canonical_pair(kind, a1, a2)
                for kind, a1, a2 in zip(kinds, g1, g2)
            ]
            full_geno = "".join(locus_genos)
            if full_geno in lethal_patterns or any(lg in lethal_patterns for lg in locus_genos):
                continue
            viable_count += 1
            geno_counts[full_geno] += 1
            pheno = "".join(
                _locus_phenotype(kind, lg) for kind, lg in zip(kinds, locus_genos)
            )
            pheno_counts[pheno] += 1

    if viable_count == 0:
        raise ValueError("all_offspring_lethal")

    payload = {
        "total_Combinations": total_combinations,
        "viable_combinations": viable_count,
        "viable_fraction": format_fraction(Fraction(viable_count, total_combinations)),
        "genotype_ratios": {
            k: format_fraction(Fraction(v, viable_count))
            for k, v in geno_counts.items()
        },
        "phenotype_ratios": {
            k: format_fraction(Fraction(v, viable_count))
            for k, v in pheno_counts.items()
        },
    }
    return {
        "engine_version": "genetics-v1",
        "status": "ok",
        "result": json.dumps(payload, ensure_ascii=False),
        "conditions": ["assumes_independent_assortment_and_complete_dominance"],
        "checked_scope": "value",
    }
