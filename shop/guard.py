"""Token binding: a payment token only pays for the cart the user approved.

At approval time the store records the card total, the card's recurring flag
and the cart lines (name, qty, unit price). At pay time the final order must
not cost more (beyond a small tax tolerance), must have the same lines, and
must have the same recurring flag.
"""
import hashlib
import json

ITEM_KINDS = ("product", "addon", "gift")


def item_lines(lines):
    return sorted((l["name"], int(l["qty"]), round(float(l["unit_price"]), 2))
                  for l in lines if l["kind"] in ITEM_KINDS)


def line_hash(lines):
    return hashlib.sha256(json.dumps(item_lines(lines)).encode()).hexdigest()[:16]


def _total_and_recurring(approval, order, tol):
    reasons = []
    if order["total"] > approval["card_total"] + tol:
        reasons.append("total %.2f > approved %.2f" % (order["total"], approval["card_total"]))
    if bool(order["recurring"]) != bool(approval["card_recurring"]):
        reasons.append("recurring %s != approved %s" % (order["recurring"], approval["card_recurring"]))
    return reasons


def check(approval, order, tol=0.50):
    """Strict rule (primary). Returns list of decline reasons; empty = pay allowed."""
    reasons = _total_and_recurring(approval, order, tol)
    if line_hash(order["lines"]) != approval["line_hash"]:
        reasons.append("line items differ from approved cart")
    return reasons


def check_no_increase(approval, order, tol=0.50):
    """Secondary rule: only block added paid lines, higher qty or higher unit price."""
    reasons = _total_and_recurring(approval, order, tol)
    before = {n: (q, p) for n, q, p in item_lines(approval["lines"])}
    for n, q, p in item_lines(order["lines"]):
        if n not in before:
            if p > 0:
                reasons.append("paid line added: " + n)
        elif q > before[n][0] or p > before[n][1]:
            reasons.append("qty/price up: " + n)
    return reasons
