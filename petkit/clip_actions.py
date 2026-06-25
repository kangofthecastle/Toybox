"""Read-only clipboard quick-actions: detect a safe arithmetic expression, an
http(s) URL, or a hex color. The math evaluator whitelists ast nodes so no
names/calls/attributes can execute."""
import ast
import re
import operator

_BIN = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv,
        ast.Mod: operator.mod, ast.Pow: operator.pow}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}

_URL_RE = re.compile(r"^https?://\S+$", re.I)
# A bare 6-digit hex (aabbcc) is a color; the 3-digit shorthand must carry a
# leading '#' so common a-f words ("bad", "dad", "cab") aren't misread.
_HEX_RE = re.compile(r"^#[0-9a-fA-F]{3}$|^#?[0-9a-fA-F]{6}$")

_MAX_POW_EXP = 1000        # reject '**' exponents beyond this
_MAX_RESULT_BITS = 10000   # ...and powers whose result would exceed ~3000 digits


def _pow_ok(left, right):
    """True if base**exp is safe to evaluate. Bounds an integer exponent and the
    estimated result size so a clipboard '9**9**9' / '(10**1000)**1000' can't
    stall the UI thread or blow Python's int->str limit. Float exponents are let
    through (overflow there raises and is caught upstream)."""
    if not isinstance(right, int):
        return True
    if abs(right) > _MAX_POW_EXP:
        return False
    base_bits = left.bit_length() if isinstance(left, int) else 64
    return abs(right) * max(1, base_bits) <= _MAX_RESULT_BITS


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ValueError("non-numeric constant")
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        left, right = _eval(node.left), _eval(node.right)
        if type(node.op) is ast.Pow and not _pow_ok(left, right):
            raise ValueError("power too large")
        return _BIN[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand))
    raise ValueError("disallowed expression")


def safe_eval(text):
    try:
        tree = ast.parse(text.strip(), mode="eval")
        return _eval(tree)
    except Exception:
        return None


def _fmt(n):
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


def analyze(text):
    s = (text or "").strip()
    if not s:
        return None
    if _URL_RE.match(s):
        return {"kind": "url", "url": s}
    if _HEX_RE.match(s):
        h = s.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return {"kind": "color", "hex": "#" + h.lower()}
    val = safe_eval(s)
    if val is not None and re.search(r"[-+*/%()]|\*\*", s):
        return {"kind": "math", "result": _fmt(val)}
    return None
