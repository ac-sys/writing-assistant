"""Word-level diff for the side-by-side view."""
import difflib
import re

TOK = re.compile(r"\s+|[A-Za-z0-9'\u2019-]+|[^\sA-Za-z0-9]")


def word_diff(a, b):
    ta, tb = TOK.findall(a), TOK.findall(b)
    sm = difflib.SequenceMatcher(None, ta, tb, autojunk=False)
    left, right = [], []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        A, B = "".join(ta[i1:i2]), "".join(tb[j1:j2])
        if op == "equal":
            left.append(["eq", A]); right.append(["eq", B])
        else:
            if A: left.append(["del", A])
            if B: right.append(["ins", B])
    changed = sum(len(x[1].split()) for x in right if x[0] == "ins")
    return {"left": left, "right": right, "similarity": round(sm.ratio(), 3),
            "words_changed": changed}
