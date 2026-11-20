"""Printed question/page ranges for the PDFs pinned in sources.json (one-based)."""

# First question that starts on each PDF page and last printed question number.
SOURCES = {
    "math": ([1, 7, 15, 19, 0], 21),
    "biology": ([1, 3, 7, 11, 16, 18, 19, 20, 21, 0], 21),
    "physics": ([1, 5, 8, 11, 14, 16, 17, 20], 20),
    "chemistry": ([1, 5, 8, 10, 12, 15, 16, 17, 18, 19, 0, 0], 19),
    "politics": ([1, 3, 7, 10, 13, 16, 17, 20, 21], 21),
    "geography": ([1, 4, 9, 13, 17, 18, 19, 0], 20),
    "history": ([1, 5, 9, 13, 17, 19, 20], 20),
    "chinese": ([], 25),
    "english": ([], 44),
}
# Shared passages, prompts and elective writing options. For Chinese the two
# elective tasks are frozen before running, consistently with the paper's rules.
GROUPS = {
    "chinese": [
        (1, 5, 1, 3),
        (6, 10, 3, 4),
        (11, 13, 4, 5),
        (14, 14, 5, 6),
        (15, 15, 6, 6),
        (16, 19, 6, 8),
        (20, 20, 8, 8),
        (21, 21, 8, 9),
        (24, 24, 9, 9),
    ],
    "english": [
        (1, 10, 1, 2),
        (11, 20, 2, 2),
        (21, 23, 3, 4),
        (24, 27, 4, 5),
        (28, 30, 5, 6),
        (31, 34, 6, 7),
        (35, 39, 7, 8),
        (40, 43, 8, 9),
        (44, 44, 9, 10),
    ],
}


def tasks(subject):
    if subject in GROUPS:
        return GROUPS[subject]
    starts, last = SOURCES[subject]
    locations = {q: p for p, q in enumerate(starts, 1) if q}

    def page(n):
        return locations[max(q for q in locations if q <= n)]

    result = []
    for n in range(1, last + 1):
        first = page(n)
        # Some geography prompts precede the first numbered line in a group.
        shared = {4: 1, 5: 1, 7: 2, 9: 2, 10: 2, 11: 3, 12: 3, 13: 3, 14: 3}
        if subject == "geography":
            first = min(first, shared.get(n, first))
        end = page(n + 1) if n < last else len(starts)
        result.append((n, n, first, end))
    return result
