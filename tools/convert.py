#!/usr/bin/env python3
"""Turns SDCC's Z80 and SM83 peephole rules into z80-test rules.

Each SDCC rule becomes one rule. A pattern variable (%1, %2, ...) that SDCC
can only bind to a number becomes a number, which one proof covers for every
value; any other becomes an operand that takes, in turn, each operand it can
stand for where it appears. The conditions become conditions of the rule,
with SDCC's own predicates spelled out over those operands as
src/SDCCpeeph.c and src/z80/peep.c evaluate them, and the registers that
notUsed() names may differ.
"""

import argparse
import itertools
import os
import re

import peeph

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CPUS = {
    'z80': ['peeph.def', 'peeph-z80.def'],
    'sm83': ['peeph-sm83.def', 'peeph.def'],
}

REG8 = ['a', 'b', 'c', 'd', 'e', 'h', 'l']
NUM = r'-?(?:0x[0-9a-fA-F]+|\d+)'
SYM = re.compile(r'\b[kox]\d+\b')  # the numbers of a rule
FLAGS = {'zf': 'ZF', 'cf': 'CF', 'sf': 'SF', 'pf': 'PVF', 'vf': 'PVF',
         'lf': 'PVF', 'nf': 'NF', 'hf': 'HF'}
NAMES = {'a', 'b', 'c', 'd', 'e', 'h', 'l', 'i', 'r', 'af', 'bc', 'de', 'hl',
         'sp', 'ix', 'iy', 'ixh', 'ixl', 'iyh', 'iyl', 'z', 'nz', 'nc', 'po',
         'pe', 'p', 'm'}
FLOW = ('jp', 'jr', 'call', 'djnz', 'ret', 'reti', 'retn', 'rst')
IGNORED = ('notVolatile', 'optimizeFor', 'labelRefCountChange',
           'labelRefCount', 'labelInRange', 'labelIsReturnOnly',
           'label5IsUncondJumpTo6', 'symmParmStack', 'newLabel', 'isPort')


class Skip(Exception):
    pass


# --- Where a variable appears ------------------------------------------------

def split_operands(text):
    out, depth, cur = [], 0, ''
    for ch in text:
        if ch == ',' and depth == 0:
            out.append(cur.strip())
            cur = ''
            continue
        depth += ch == '('
        depth -= ch == ')'
        cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def split_line(line):
    """Mnemonic and operands of a pattern line."""
    parts = line.split(None, 1)
    return parts[0], split_operands(parts[1]) if len(parts) > 1 else []


def is_flow(mnem, conds):
    """Whether a pattern's mnemonic transfers control, also when it is a
    variable that same() limits to such mnemonics."""
    if mnem.lower() in FLOW:
        return True
    return any(name == 'same' and args[0] == mnem and
               all(a in FLOW for a in args[1:]) for name, args in conds)


def contexts(lines, conds=()):
    """For each variable, the kinds of places it appears in."""
    ctx = {}

    def add(var, kind):
        ctx.setdefault(int(var), set()).add(kind)

    for line in lines:
        if line.endswith(':'):
            for v in re.findall(r'%(\d+)', line):
                add(v, 'label')
            continue
        mnem, ops = split_line(line)
        for v in re.findall(r'%(\d+)', mnem):
            add(v, 'opcode')
        if is_flow(mnem, conds):
            for i, op in enumerate(ops):
                m = re.fullmatch(r'%(\d+)', op)
                if not m:
                    for v in re.findall(r'%(\d+)', op):
                        add(v, 'inner')
                elif mnem.lower() in ('ret', 'reti', 'retn') or \
                        i < len(ops) - 1:
                    add(m.group(1), 'cc')
                else:
                    add(m.group(1), 'label')
            continue
        ops_of = [set(args[1:]) for name, args in conds
                  if name == 'same' and args[0] == mnem]
        bit_op = mnem in ('bit', 'set', 'res') or any(
            o <= {'bit', 'set', 'res'} for o in ops_of)
        for i, op in enumerate(ops):
            # An opcode that can be BIT, SET or RES takes a bit number first.
            if i == 0 and not bit_op and any(o & {'bit', 'set', 'res'}
                                             for o in ops_of):
                for v in re.findall(r'%(\d+)', op):
                    add(v, 'bit number')
            if bit_op and i == 0:
                for v in re.findall(r'%(\d+)', op):
                    add(v, 'bit')
                continue
            m = re.fullmatch(r'%(\d+)', op)
            if m:
                add(m.group(1), 'full')
                continue
            m = re.fullmatch(r'#%(\d+)', op)
            if m:
                add(m.group(1), 'imm')
                continue
            m = re.fullmatch(r'%(\d+) \(%(\d+)\)', op)
            if m:
                add(m.group(1), 'off')
                add(m.group(2), 'idx')
                continue
            m = re.fullmatch(r'%(\d+) \((ix|iy|sp)\)', op)
            if m:
                add(m.group(1), 'off')
                continue
            m = re.fullmatch(r'\(%(\d+)\)', op)
            if m:
                add(m.group(1), 'inner')
                continue
            m = re.fullmatch(r'\(#%(\d+)\)', op)
            if m:
                add(m.group(1), 'addr')
                continue
            m = re.fullmatch(r'\(?#%(\d+) *[-+] *(%(\d+)|\w+)\)?', op)
            if m:
                add(m.group(1), 'sym')
                if m.group(3):
                    add(m.group(3), 'small')
                continue
            # Anything else after '#' is an expression of numbers.
            kind = 'sym' if re.match(r'\(?#', op) else 'full'
            for v in re.findall(r'%(\d+)', op):
                add(v, kind)
    return ctx


NUMBER_KINDS = {'imm', 'off', 'addr', 'sym', 'small'}


# --- SDCC's predicates, on the text SDCC binds -------------------------------

def base_name(op):
    if op in ('d', 'e', '(de)'):
        return 'de'
    if op in ('b', 'c', '(bc)'):
        return 'bc'
    if op in ('h', 'l', '(hl)', '(hl+)', '(hl-)'):
        return 'hl'
    if op in ('iyh', 'iyl') or 'iy' in op:
        return 'iy'
    if op in ('ixh', 'ixl') or 'ix' in op:
        return 'ix'
    if op == 'a':
        return 'af'
    return op


def is_reg(x):
    return x in REG8


def is_pair(x):
    return x in ('bc', 'de', 'hl', 'ix', 'iy')


def can_assign(dst, src, exotic, cpu):
    sm83 = cpu == 'sm83'
    if exotic is not None:
        if exotic in ('ix', 'iy'):
            return is_reg(dst)
        if src in ('ix', 'iy'):
            return is_reg(exotic) or exotic.startswith('#')
        return False
    if is_reg(dst) and is_reg(src):
        return True
    if is_reg(dst) and src.startswith('#'):
        return True
    if is_reg(dst) and src == '(hl)':
        return True
    if dst == '(hl)' and is_reg(src):
        return True
    if dst == 'a' and src in ('(bc)', '(de)', '(hl+)', '(hl-)'):
        return True
    if (dst in ('(bc)', '(de)') or src in ('(hl+)', '(hl-)')) and src == 'a':
        return True
    if (is_reg(dst) or is_pair(dst) or src == 'sp') and src.startswith('#'):
        return True
    if (dst == 'a' or (not sm83 and (is_pair(dst) or src == 'sp'))) and \
            src.startswith('(#'):
        return True
    if dst.startswith('(#') and (src == 'a' or (not sm83 and is_pair(src))
                                 or src == 'sp'):
        return True
    if dst == '(hl)' and src.startswith('#'):
        return True
    if dst == 'sp' and src in ('hl', 'ix', 'iy') or \
            dst in ('hl', 'ix', 'iy') and src == 'sp':
        return True
    return False


def can_join(regs, cpu):
    if len(regs) != 2:
        return None
    hi, lo = regs
    if not hi or not lo:
        if not hi and not lo:
            return None
        dst = base_name(hi or lo)
    else:
        dst = hi + lo
    if dst in ('ixhixl', 'iyhiyl'):
        if cpu == 'sm83':
            return None
        dst = dst[:2]
    return dst if is_pair(dst) else None


def immd_get(s):
    s = s.strip()
    sign = 1
    while s and not s[0].isdigit():
        if s[0] == '-':
            sign = -sign
        elif s[0] != '+':
            return None
        s = s[1:]
    if s[:2].lower() == '0x':
        m = re.match(r'[0-9a-fA-F]+', s[2:])
        return sign * int(m.group(0), 16) if m else None
    m = re.match(r'\d+', s)
    return sign * int(m.group(0)) if m else None


def is_literal(s):
    return bool(SYM.fullmatch(s) or re.fullmatch(
        r'[-+]?(0x[0-9a-fA-F]+|0b[01]+|0o[0-7]+|\d+)', s))


def num_expr(text):
    """The number SDCC reads from an operand's text, as an expression: a
    number of the rule or a decimal number. None if it is neither."""
    if SYM.fullmatch(text):
        return text
    n = immd_get(text)
    return None if n is None else str(n)


def text_eq(a, b):
    """Whether two operands are the same text: True, False, or an
    expression over the numbers in them."""
    if not SYM.search(a) and not SYM.search(b):
        return a == b
    if SYM.search(b) and not SYM.search(a):
        a, b = b, a
    parts = SYM.split(a)
    names = SYM.findall(a)
    if SYM.search(b):
        if SYM.split(b) != parts:
            return False
        eqs = [f'{x} == {y}' for x, y in zip(names, SYM.findall(b)) if x != y]
    else:
        m = re.fullmatch(f'({NUM})'.join(map(re.escape, parts)), b)
        if not m:
            return False
        eqs = [f'{x} == {immd_get(v)}' for x, v in zip(names, m.groups())]
    return ' && '.join(eqs) if eqs else True


def not_related(vals):
    """operandsNotRelated: SDCC takes the arguments last to first, and
    replaces the first of each pair by its base name before it looks for two
    memory operands."""
    rev = vals[::-1]
    conds = []
    for i in range(len(rev)):
        a = base_name(rev[i])
        for b in rev[i + 1:]:
            if ('(' in a or '[' in a) and ('(' in b or '[' in b):
                return False
            eq = text_eq(a, base_name(b))
            if eq is True:
                return False
            if eq is not False:
                conds.append(f'!({eq})')
    return ' && '.join(conds) if conds else True


def dead_names(name, cpu):
    """The fields notUsed(name) lets differ, or None if it never holds."""
    if name == 'af':
        return {'A'} | dead_names('f', cpu)
    if name == 'f':
        return set().union(*(dead_names(f, cpu) for f in
                             ('zf', 'cf', 'sf', 'pf', 'nf', 'hf')))
    if name in FLAGS:
        if cpu == 'sm83' and FLAGS[name] in ('SF', 'PVF'):
            return set()
        return {FLAGS[name]}
    if name in REG8:
        return {name.upper()}
    if name in ('bc', 'de', 'hl'):
        return {name.upper()}
    if name in ('ix', 'ixh', 'ixl') and cpu == 'z80':
        return {'IX'}
    if name in ('iy', 'iyh', 'iyl') and cpu == 'z80':
        return {'IY'}
    if name == 'sp':
        return {'SP'}
    return None


def bit_position(n, bits, complement):
    """The bit immdInRange's singleSetBit or singleResetBit gives, as an
    expression over n; None if bits is out of range."""
    if not 1 <= bits <= 32:
        return None, None
    mask = (1 << bits) - 1
    v = f'(~{n} & {mask})' if complement else n
    holds = f'{n} == ({n} & {mask}) && {v} != 0 && ({v} & ({v} - 1)) == 0'
    return holds, v


# --- Variables -----------------------------------------------------------------

class Var:
    """A pattern variable: an operand that takes each of its choices, each a
    pair of the text z80-test assembles and the text SDCC binds; a number; or
    a label."""

    def __init__(self, n, kind, choices=(), numbers=None, ntype=None):
        self.n = n
        self.kind = kind
        self.name = {'operand': 'v', 'number': 'k', 'label': 'l'}[kind] + \
            str(n)
        self.choices = list(choices)
        self.numbers = numbers or {}  # number variables the choices use
        self.ntype = ntype


def full_choices(n, cpu):
    regs = REG8 + ['bc', 'de', 'hl', 'sp', 'af', '(hl)', '(de)', '(bc)']
    regs += ['ix', 'iy'] if cpu == 'z80' else ['(hl+)', '(hl-)']
    out = [(r, r) for r in regs]
    k = f'k{n}'
    out += [(f'#{k}', f'#{k}'), (f'({k})', f'(#{k})')]
    numbers = {k: 'u16'}
    if cpu == 'z80':
        d = f'o{n}'
        out += [(f'{d} (ix)', f'{d} (ix)'), (f'{d} (iy)', f'{d} (iy)')]
        numbers[d] = 's8'
    return out, numbers


def inner_choices(n, cpu):
    regs = ['hl', 'de', 'bc', 'sp', 'c'] + (['ix', 'iy'] if cpu == 'z80'
                                            else [])
    k = f'k{n}'
    return [(r, r) for r in regs] + [(k, f'#{k}')], {k: 'u16'}


def operand_choices(n, kinds, rule, cpu):
    """The choices of an operand variable that appears in kinds of places."""
    sets = []
    numbers = {}
    for kind in sorted(kinds - {'bit number'}):
        if kind == 'full':
            c, nums = full_choices(n, cpu)
        elif kind == 'inner':
            c, nums = inner_choices(n, cpu)
        elif kind == 'idx':
            c, nums = ([('ix', 'ix'), ('iy', 'iy')] if cpu == 'z80' else []), {}
        elif kind == 'bit':
            c, nums = [(str(b), str(b)) for b in range(8)], {}
        elif kind == 'cc':
            cc = ['z', 'nz', 'c', 'nc'] + (['po', 'pe', 'p', 'm']
                                          if cpu == 'z80' else [])
            c, nums = [(x, x) for x in cc], {}
        else:
            raise Skip(f'%{n} is both a number and an operand')
        sets.append(c)
        numbers.update(nums)
    common = [c for c in sets[0] if all(c in s for s in sets[1:])]
    if 'bit number' in kinds:
        common += [(str(b), str(b)) for b in range(8)]
    # same() with only literal operands narrows a variable to them.
    for name, args in rule.conds:
        if name == 'same' and args[0] == f'%{n}' and \
                not any(a.startswith('%') for a in args[1:]):
            listed = [(asm_text(a), a) for a in args[1:]]
            common = [c for c in listed if c in common] if common and \
                kinds - {'bit number'} != {'opcode'} else listed
    if not common:
        raise Skip(f'%{n} has no operand on the {cpu.upper()}')
    used = {m for c, _ in common for m in SYM.findall(c)}
    return common, {k: t for k, t in numbers.items() if k in used}


def number_type(n, kinds, rule):
    """The values a number variable takes: a displacement or an offset from
    SP is signed, anything else is unsigned."""
    signed = re.compile(rf'(ldhl\s+sp\s*,\s*#%{n}\b|add\s+sp\s*,\s*#%{n}\b|'
                        rf'%{n} \()')
    lines = rule.before + rule.after
    s = sum(1 for l in lines if signed.search(l))
    u = sum(len(re.findall(rf'%{n}\b', l)) for l in lines) - s
    if s and u:
        return '-128..65535'
    return 's8' if s else 'u16'


def asm_text(op):
    """An operand as SDCC writes it, as LLVM's assembler reads it."""
    m = re.fullmatch(r'\(#(.*)\)', op)
    return '(' + m.group(1) + ')' if m else op


# --- Conditions -------------------------------------------------------------------

def quote(text):
    """An operand in a condition of z80-test."""
    if text in NAMES or re.fullmatch(NUM, text):
        return text
    return f"'{text}'"


def member(var, chosen):
    """A condition that var is one of the chosen texts."""
    allc = [c for c, _ in var.choices]
    if set(chosen) >= set(allc):
        return True
    rest = [c for c in allc if c not in chosen]
    if len(chosen) <= len(rest):
        terms = [f'{var.name} == {quote(c)}' for c in chosen]
        return terms[0] if len(terms) == 1 else '(' + ' || '.join(terms) + ')'
    terms = [f'{var.name} != {quote(c)}' for c in rest]
    return terms[0] if len(terms) == 1 else '(' + ' && '.join(terms) + ')'


def top(expr, op):
    """Whether op joins the outermost terms of expr."""
    depth, quoted = 0, False
    for i, ch in enumerate(expr):
        if ch == "'":
            quoted = not quoted
        elif not quoted:
            depth += {'(': 1, ')': -1}.get(ch, 0)
            if depth == 0 and expr.startswith(op, i):
                return True
    return False


def and_(*xs):
    xs = [x for x in xs if x is not True]
    if any(x is False for x in xs):
        return False
    if not xs:
        return True
    return xs[0] if len(xs) == 1 else ' && '.join(
        f'({x})' if top(x, '||') else x for x in xs)


def or_(xs):
    xs = [x for x in xs if x is not False]
    if any(x is True for x in xs):
        return True
    if not xs:
        return False
    return xs[0] if len(xs) == 1 else ' || '.join(
        f'({x})' if top(x, '&&') else x for x in xs)


def relation(args, pred, allowed=None):
    """A condition that holds where pred does. args are variables or literal
    texts; pred takes the SDCC texts of a choice of each and returns True,
    False or an expression over the numbers. allowed gets, for each operand
    variable, the choices that can meet it."""
    ops = []
    for a in args:
        if isinstance(a, Var) and a.kind == 'operand' and a not in ops:
            ops.append(a)

    def text(a, pick):
        if a is None or not isinstance(a, Var):
            return a
        if a.kind == 'operand':
            return pick[ops.index(a)][1]
        return a.name

    def factor(prefix):
        if len(prefix) == len(ops):
            r = pred([text(a, prefix) for a in args])
            if r is not False and allowed is not None:
                for v, c in zip(ops, prefix):
                    allowed.setdefault(v.n, set()).add(c[0])
            return r
        v = ops[len(prefix)]
        groups = {}
        for c in v.choices:
            r = factor(prefix + [c])
            if r is not False:
                groups.setdefault(r, []).append(c[0])
        return or_([and_(member(v, cs), r) for r, cs in groups.items()])

    out = factor([])
    if allowed is not None:
        for v in ops:
            allowed.setdefault(v.n, set())
    return out


class Rule:
    """A rule of z80-test being written for an SDCC rule."""

    def __init__(self):
        self.vars = {}
        self.conds = []  # (condition, the SDCC condition it comes from)
        self.dead = set()
        self.dead_vars = []
        self.assumed = []  # conditions SDCC's code is assumed to meet
        self.allowed = []  # for each condition, the choices that can meet it


def relation_of(r, args, pred):
    allowed = {}
    r.allowed.append(allowed)
    return relation(args, pred, allowed)


def arg(r, a):
    """A condition's argument: a variable, None for one that nothing uses,
    or a literal text."""
    if a.startswith('%'):
        return r.vars.get(int(a.lstrip('%x')))
    return a


def translate(r, name, args, cpu, text):
    """Adds what an SDCC condition says to r."""
    if name in IGNORED:
        return
    vals = [arg(r, a) for a in args]
    outs = {'canSplitReg': (1, 2), 'canJoinRegs': (len(args) - 1,),
            'immdInRange': (5,), 'unusedReg': (0,)}.get(name, ())
    for k, (a, v) in enumerate(zip(args, vals)):
        if a.startswith('%') and v is None and k not in outs:
            raise Skip(f'{name}() of a variable nothing binds')
    # An output that the match binds is only read: SDCC binds a variable
    # once, and keeps the value it has.
    for k in outs:
        if k < len(vals) and isinstance(vals[k], Var) and \
                vals[k].n not in r.bound:
            vals[k] = None

    def add(cond):
        if cond is False:
            raise Skip(f'{name}() never holds')
        if cond is not True:
            r.conds.append((cond, text))

    if name == 'notUsed' or name == 'notUsedFrom':
        for v in vals[1 if name == 'notUsedFrom' else 0:]:
            if isinstance(v, Var):
                if v.kind != 'operand':
                    raise Skip(f'{name}() of a {v.kind}')
                r.dead_vars.append(v)
                continue
            d = dead_names(v, cpu)
            if d is None:
                raise Skip(f'{name}({v}) never holds')
            r.dead |= d
    elif name in ('same', 'notSame') and not any(
            isinstance(v, Var) and v.kind == 'label' for v in vals):
        ops = [(v.name, True) if isinstance(v, Var) else
               (quote(asm_text(v)), False) for v in vals]
        if name == 'same':
            add(' || '.join(f'{ops[0][0]} == {o}' for o, _ in ops[1:]))
        else:
            add(' && '.join(f'{a} != {b}' for (a, x), (b, y) in
                            itertools.combinations(ops, 2) if x or y)
                or True)
    elif name in ('same', 'notSame'):
        def pred(t):
            if name == 'same':
                return or_([text_eq(t[0], x) for x in t[1:]])
            return and_(*[True if e is False else False if e is True
                          else f'!({e})'
                          for e in (text_eq(a, b) for a, b in
                                    itertools.combinations(t, 2))])
        add(relation_of(r, vals, pred))
    elif name == 'operandsNotRelated':
        add(relation_of(r, vals, not_related))
    elif name == 'operandsLiteral':
        add(relation_of(r, vals, lambda t: all(map(is_literal, t))))
    elif name == 'canAssign':
        exotic = len(vals) == 3
        add(relation_of(r, vals, lambda t: can_assign(
            t[0], t[1], t[2] if exotic else None, cpu)))
    elif name == 'canSplitReg':
        def pred(t):
            if t[0] not in ('bc', 'de', 'hl'):
                return False
            return all(o is None or o == t[0][k]
                       for k, o in enumerate(t[1:3]))
        add(relation_of(r, vals[:3], pred))
    elif name == 'canJoinRegs':
        regs, out = vals[:-1], vals[-1]
        unordered = regs and regs[0] == 'unordered'
        if unordered:
            regs = regs[1:]

        def pred(t):
            got = t[:-1]
            perms = itertools.permutations(sorted(got)) if unordered \
                else [got]
            for p in perms:
                dst = can_join(list(p), cpu)
                if dst:
                    return t[-1] is None or t[-1] == dst
            return False
        add(relation_of(r, regs + [out], pred))
    elif name == 'immdInRange':
        lo, hi, op = immd_get(args[0]), immd_get(args[1]), args[2]
        if lo is None or hi is None:
            raise Skip('immdInRange() with bounds that are not numbers')
        lo, hi = sorted((lo, hi))

        def pred(t):
            left, right, out = num_expr(t[0]), num_expr(t[1]), t[2]
            if left is None or right is None:
                return False
            if op in ('+', '-', '*', '/', '%', '&', '^', '|'):
                e = f'({left} {op} {right})'
                parts = [f'{lo} <= {e} && {e} <= {hi}']
                if op in ('/', '%') and SYM.fullmatch(right):
                    parts.insert(0, f'{right} != 0')
                elif op in ('/', '%') and int(right) == 0:
                    return False
            elif op in ('singleSetBit', 'singleResetBit'):
                if not re.fullmatch(NUM, right):
                    raise Skip(f'immdInRange() {op} of a width that is not '
                               'a number')
                holds, v = bit_position(left, int(right),
                                        op == 'singleResetBit')
                if holds is None:
                    return False
                if out is None:
                    return and_(holds, f'{1 << max(lo, 0)} <= {v}',
                                f'{v} <= {1 << max(hi, 0)}' if hi >= 0
                                else False)
                return and_(holds, f'{v} == 1 << {out}',
                            f'{lo} <= {out} && {out} <= {hi}')
            elif op == 'swap':
                if not re.fullmatch(NUM, right):
                    raise Skip('immdInRange() swap of a width that is not a '
                               'number')
                bits = int(right)
                if bits < 1 or bits > 32 or bits & 1:
                    return False
                mask = (1 << bits) - 1
                sh = bits // 2
                e = f'((({left} << {sh}) | ({left} >> {sh})) & {mask})'
                parts = [f'{left} == ({left} & {mask})',
                         f'{lo} <= {e} && {e} <= {hi}']
            else:
                raise Skip(f'immdInRange() operator {op}')
            if out is not None:
                parts.append(f'{out} == {e}')
            return and_(*parts)

        add(relation_of(r, vals[3:6], pred))
    elif name == 'unusedReg':
        if vals[0] is None:
            raise Skip('unusedReg() of a variable the match binds')
        add(relation_of(r, vals, lambda t: or_(
            [text_eq(t[0], x) for x in t[1:]])))
        r.dead_vars.append(vals[0])
    else:
        raise Skip(f'condition {name}')


# --- Rules ------------------------------------------------------------------

def to_asm(line):
    """A line of a pattern, with its variables named, as LLVM's assembler
    reads it."""
    if line.endswith(':'):
        return line
    mnem, ops = split_line(line)
    return mnem.lower() + ('\t' + ', '.join(asm_text(o) for o in ops)
                           if ops else '')


def lift_exprs(lines, fresh):
    """Gives each operand that combines numbers a number of its own: the
    assembler can only relocate one symbol plus a number. fresh maps each
    such expression to its name."""
    def value(v):
        v = v.strip()
        if not SYM.search(v) or \
                re.fullmatch(f'[kox]\\d+(\\s*[-+]\\s*{NUM})?', v):
            return v
        if '#' in v or re.search(r'[A-Za-z_]', re.sub(r'0x[0-9a-fA-F]+', '',
                                                      SYM.sub('', v))):
            return v
        if v not in fresh:
            fresh[v] = f'x{len(fresh)}'
        return fresh[v]

    out = []
    for l in lines:
        if l.endswith(':'):
            out.append(l)
            continue
        mnem, ops = split_line(l)
        new = []
        for op in ops:
            m = re.fullmatch(r'#(.+)', op)
            n = re.fullmatch(r'\((.+)\)', op)
            d = re.fullmatch(r'(.+?) \((ix|iy|sp)\)', op)
            if m:
                op = '#' + value(m.group(1))
            elif n and SYM.search(n.group(1)):
                op = f'({value(n.group(1))})'
            elif d:
                op = f'{value(d.group(1))} ({d.group(2)})'
            else:
                op = value(op)
            new.append(op)
        out.append(mnem + ('\t' + ', '.join(new) if new else ''))
    return out


def label_stubs(rule, lines, r):
    """Code for the labels a side jumps to that stand for something: a
    return, or a jump to %6."""
    stubs = []
    defined = {l[:-1] for l in lines if l.endswith(':')}
    for name, args in rule.conds:
        if name == 'labelIsReturnOnly':
            v = r.vars.get(int(args[0].lstrip('%')))
            if v and v.name not in defined:
                stubs += [f'{v.name}:', 'ret']
        if name == 'label5IsUncondJumpTo6' and 5 in r.vars and 6 in r.vars:
            if r.vars[5].name not in defined:
                stubs += [f'{r.vars[5].name}:', f'jp\t{r.vars[6].name}']
    return ['halt'] + stubs if stubs else []


def convert(rule, cpu):
    """The rule of z80-test for an SDCC rule, as lines of text."""
    lines = rule.before + rule.after
    if any(split_line(l)[0] == 'assert' for l in lines):
        raise Skip('an assertion, not an instruction')
    for name, args in rule.conds:
        if name == 'isPort' and cpu not in args:
            raise Skip('for other ports')
    r = Rule()
    every = contexts(lines, rule.conds)
    free = set(contexts(rule.before, rule.conds))
    # Variables a condition binds.
    binders = {}
    for name, args in rule.conds:
        vs = [int(a[2:] if a.startswith('%x') else a[1:]) for a in args
              if a.startswith('%')]
        if name == 'canSplitReg':
            out = vs[1:]
        elif name == 'canJoinRegs':
            out = vs[-1:]
        elif name == 'immdInRange':
            out = [int(args[5].lstrip('%x'))]
        elif name in ('unusedReg', 'newLabel'):
            out = vs[:1]
        elif name == 'label5IsUncondJumpTo6':
            out = [6]
        else:
            out = []
        for v in out:
            if v > 0 and v not in free:
                binders.setdefault(v, (name, args))
    r.bound = set(binders)
    # Variables that conditions read, other than those they bind.
    read = set()
    for name, args in rule.conds:
        for a in args:
            if a.startswith('%') and binders.get(int(a.lstrip('%x')), (
                    None, None))[1] is not args:
                read.add(int(a.lstrip('%x')))
    for n in sorted(set(every) | set(binders)):
        kinds = every.get(n, set())
        binder, bargs = binders.get(n, (None, None))
        if 'label' in kinds or binder in ('newLabel',
                                          'label5IsUncondJumpTo6'):
            r.vars[n] = Var(n, 'label')
        elif 'opcode' in kinds:
            same = [args for name, args in rule.conds
                    if name == 'same' and args[0] == f'%{n}']
            if not same:
                raise Skip(f'%{n} is an opcode without same()')
            r.vars[n] = Var(n, 'operand', [(a, a) for a in same[0][1:]])
        elif kinds and kinds <= NUMBER_KINDS:
            r.vars[n] = Var(n, 'number', ntype=number_type(n, kinds, rule))
        elif kinds & NUMBER_KINDS and kinds - NUMBER_KINDS <= {'inner'}:
            # A number that is also written as the address in parentheses.
            r.vars[n] = Var(n, 'number', ntype='u16')
        elif kinds and binder not in ('canSplitReg', 'canJoinRegs',
                                      'unusedReg'):
            choices, numbers = operand_choices(n, kinds, rule, cpu)
            r.vars[n] = Var(n, 'operand', choices, numbers)
        elif n not in read and not kinds:
            # Bound by a condition and used nowhere.
            r.vars[n] = None
        elif binder == 'immdInRange':
            lo, hi = sorted((immd_get(bargs[0]) or 0, immd_get(bargs[1]) or 0))
            r.vars[n] = Var(n, 'number', ntype=f'{lo}..{hi}')
        elif binder in ('canSplitReg', 'canJoinRegs', 'unusedReg'):
            # What the condition can bind, where the variable can go.
            if binder == 'canSplitReg':
                regs = ['b', 'c', 'd', 'e', 'h', 'l']
            elif binder == 'canJoinRegs':
                regs = ['bc', 'de', 'hl'] + (['ix', 'iy'] if cpu == 'z80'
                                             else [])
            else:
                regs = bargs[1:]
                if any(a.startswith('%') for a in regs):
                    raise Skip('unusedReg() of variables')
            choices = [(x, x) for x in regs]
            if kinds:
                fits, _ = operand_choices(n, kinds, rule, cpu)
                choices = [c for c in choices if c in fits]
            if not choices:
                raise Skip(f'%{n} has no operand {binder}() binds')
            r.vars[n] = Var(n, 'operand', choices)
        else:
            raise Skip(f'%{n} is bound by {binder}()')
    for n in [n for n, v in r.vars.items() if v is None]:
        del r.vars[n]
        r.bound.discard(n)
    for n in every:
        if n not in free and n not in binders:
            raise Skip(f'%{n} has no value')

    # A variable only takes the choices that can meet every condition on it,
    # and the conditions are written for those.
    while True:
        r.conds, r.dead, r.dead_vars, r.allowed = [], set(), [], []
        for name, args in rule.conds:
            shown = ' '.join(a if a.startswith('%') or re.fullmatch(NUM, a)
                             else f"'{a}'" for a in args)
            translate(r, name, args, cpu, f'{name}({shown})')
        narrowed = False
        for allowed in r.allowed:
            for n, ok in allowed.items():
                v = r.vars[n]
                fit = [c for c in v.choices if c[0] in ok]
                if not fit:
                    raise Skip(f'no operand of %{n} meets the conditions')
                if len(fit) < len(v.choices):
                    v.choices = fit
                    narrowed = True
        if not narrowed:
            break
    for v in r.vars.values():
        used = {m for c, _ in v.choices for m in SYM.findall(c)}
        v.numbers = {k: t for k, t in v.numbers.items() if k in used}

    def named(l):
        return re.sub(r'%(\d+)', lambda m: r.vars[int(m.group(1))].name, l)

    fresh = {}
    before = lift_exprs([to_asm(named(l)) for l in rule.before], fresh)
    after = lift_exprs([to_asm(named(l)) for l in rule.after], fresh)
    before += label_stubs(rule, before, r)
    after += label_stubs(rule, after, r)

    # SDCC's code has no load of a register from itself.
    for l in rule.before:
        m = re.fullmatch(r'ld\s+(%\d+|\w+)\s*,\s*(%\d+|\w+)', l)
        if m and m.group(1) != m.group(2) and any(
                g.startswith('%') for g in m.groups()):
            a, b = (r.vars[int(g[1:])] if g.startswith('%') else g
                    for g in m.groups())
            if isinstance(a, Var) and a.kind != 'operand' or \
                    isinstance(b, Var) and b.kind != 'operand':
                continue
            na = a.name if isinstance(a, Var) else quote(a)
            nb = b.name if isinstance(b, Var) else quote(b)
            r.assumed.append((f'{na} != {nb}', 'not ld x, x'))

    # The bit number of BIT, SET and RES is a number, not a symbol.
    for l in rule.before + rule.after:
        m = re.fullmatch(r'%(\d+)\s+%(\d+)\s*,.*', l)
        if not m:
            continue
        op, first = r.vars[int(m.group(1))], r.vars[int(m.group(2))]
        bits = [c for c, _ in op.choices if c in ('bit', 'set', 'res')]
        if bits and first.kind == 'operand':
            cond = or_([and_(*[f"{op.name} != '{c}'" for c in bits]),
                        member(first, [c for c, _ in first.choices
                                       if re.fullmatch(r'[0-7]', c)])])
            if cond is not True and (cond, 'a bit number') not in r.assumed:
                r.assumed.append((cond, 'a bit number'))

    out = []
    order = [v for _, v in sorted(r.vars.items())]
    numbers = {}
    for v in order:
        if v.kind == 'operand':
            out.append(f'    for: {v.name} in ' +
                       ' | '.join(c for c, _ in v.choices))
            numbers.update(v.numbers)
        elif v.kind == 'number':
            numbers[v.name] = v.ntype
    for e in fresh.values():
        numbers[e] = '-32768..65535'
    if numbers:
        groups = {}
        for k in sorted(numbers, key=lambda k: (k[0], int(k[1:]))):
            groups.setdefault(numbers[k], []).append(k)
        out.append('    for: ' + '; '.join(f'{", ".join(ks)} in {t}'
                                           for t, ks in groups.items()))
    for cond, src in r.conds:
        out.append(f'    if: {cond}  // {src}')
    for e, name in fresh.items():
        out.append(f'    if: {name} == {e}')
    for cond, why in r.assumed:
        out.append(f'    if: {cond}  // {why}')
    out.append('    before:')
    out += [f'        {l}' for l in before]
    out.append('    after:')
    out += [f'        {l}' for l in after]
    return out, r


def dead_line(r, flags):
    dead = set(r.dead)
    if not flags:
        dead.add('F')
    items = sorted(dead) + [v.name for v in r.dead_vars]
    sp = 'SP' in dead or any(any(c == 'sp' for c, _ in v.choices)
                             for v in r.dead_vars)
    if not sp:
        items.append('below SP')
    return '    dead: ' + ', '.join(items)


def all_flags_dead(r, cpu):
    flags = {'ZF', 'HF', 'NF', 'CF'} | ({'SF', 'PVF'} if cpu == 'z80'
                                        else set())
    return flags <= r.dead


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('out', nargs='?', default=os.path.join(REPO, 'rules'),
                    help='directory for the rule files (default: rules)')
    ap.add_argument('--sdcc', default=os.path.join(REPO, 'sdcc'),
                    help='SDCC source tree (default: the submodule)')
    args = ap.parse_args()
    src = os.path.join(args.sdcc, 'src', 'z80')
    os.makedirs(args.out, exist_ok=True)
    for cpu, files in CPUS.items():
        texts = {True: [], False: []}
        skipped, count = [], 0
        for name in files:
            stem = name.replace('.def', '')
            for rule in peeph.load(os.path.join(src, name)):
                where = f'{name}:{rule.line}'
                try:
                    body, r = convert(rule, cpu)
                except Skip as e:
                    skipped.append(f'{where}: {e}')
                    continue
                count += 1
                head = [f'// {where}: {rule.note}']
                if rule.cond_text:
                    head.append(f'// if {rule.cond_text}')
                for flags in (True, False):
                    if not flags and all_flags_dead(r, cpu):
                        continue
                    texts[flags] += [''] + head + [f'rule {stem}-{rule.line}'] \
                        + body + [dead_line(r, flags)]
        for flags in (True, False):
            path = os.path.join(args.out,
                                f'{cpu}{"" if flags else "-noflags"}.rules')
            with open(path, 'w') as f:
                f.write(f'// SDCC peephole rules for the {cpu.upper()}, made '
                        'by convert.py' + ('' if flags else ', without the '
                                           'flags') + '.\n')
                f.write('\n'.join(texts[flags]) + '\n')
        with open(os.path.join(args.out, f'{cpu}-skipped.txt'), 'w') as f:
            f.write('\n'.join(skipped) + '\n')
        print(f'{cpu}: {count} rules, {len(skipped)} skipped')


if __name__ == '__main__':
    main()
