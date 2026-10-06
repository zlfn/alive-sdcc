#!/usr/bin/env python3
"""Reads the results of run.sh.

summary: one line for each failing rule: how many of its cases fail, what
the counterexamples shown differ in, how many of them have a pointer or an
index register near SP or two memory operands based on different registers
that overlap, which SDCC's code may never produce, and how many cases fail
without the flags.

show: each failing rule as SDCC writes it, as convert.py wrote it, and its
first counterexample, with the first that fails without the flags.
"""

import argparse
import os
import re
from collections import Counter, OrderedDict

import peeph

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STACK_OPS = ('push', 'pop', 'call', 'ret', 'rst')
SYM = re.compile(r'\b[kox]\d+\b')


def load_rules(path):
    """The rules of a file, by name, with their text."""
    rules, cur, side = OrderedDict(), None, None
    for line in open(path):
        line = line.rstrip('\n')
        m = re.match(r'rule (\S+)', line)
        if m:
            cur = rules[m.group(1)] = {'before': [], 'after': [],
                                       'text': [line]}
            side = None
            continue
        if cur is None or not line.startswith('    '):
            continue
        cur['text'].append(line)
        t = line.strip()
        if t in ('before:', 'after:'):
            side = t[:-1]
        elif t.startswith('dead:'):
            side = None
        elif side:
            cur[side].append(t)
    return rules


def load_results(path):
    """What z80-test said about each rule: whether it holds, how many of its
    cases fail of how many, and the cases it shows."""
    res, cur, case, last = {}, None, None, None
    if not os.path.exists(path):
        return res
    for line in open(path):
        line = line.rstrip('\n')
        m = re.match(r'(\S+) +(ok|FAIL)\b *(.*)', line)
        if m:
            cur = res[m.group(1)] = {'ok': m.group(2) == 'ok', 'note': '',
                                     'failed': 0, 'unproven': 0, 'cases': 0,
                                     'shown': [],
                                     'least': 'at least' in m.group(3)}
            case = None
            text = m.group(3)
            n = re.search(r'counterexample in (?:at least )?(\d+) of (\d+) '
                          r'cases(?:, (\d+) not proved)?', text)
            u = re.search(r'(\d+) of (\d+) cases not proved', text)
            p = re.search(r'proved (\d+) cases?', text)
            if n:
                cur['failed'], cur['cases'] = int(n.group(1)), int(n.group(2))
                cur['unproven'] = int(n.group(3) or 0)
            elif u:
                cur['unproven'], cur['cases'] = int(u.group(1)), int(u.group(2))
            elif p:
                cur['cases'] = int(p.group(1))
            continue
        if cur is None or not line.startswith('  '):
            continue
        t = line.strip()
        key = t.split()[0] if t else ''
        if key == 'case' or (key in ('Alive2:', 'reason') and
                             (case is None or key in case)):
            case = {}
            cur['shown'].append(case)
        if case is None:
            cur['note'] = cur['note'] or t
            continue
        if key in ('case', 'Alive2:', 'reason', 'from', 'number', 'before',
                   'after'):
            case[key] = t[len(key):].strip()
            last = key
        elif last == 'from':
            case['memory'] = t
    return res


def choices(text):
    """The operands of a case: 'v1=bc v2=o2 (ix)' as a dict."""
    return dict(re.findall(r'(\w+)=(.*?)(?= \w+=|$)', text))


def fields(text):
    return dict(re.findall(r'(\S+)=(\S+)', text))


def case_code(rule, case):
    """The lines of both sides of a case, with its operands and numbers."""
    ops = choices(case.get('case', ''))
    nums = fields(case.get('number', ''))

    def value(m):
        v = nums.get(m.group(0))
        if v is None:
            return m.group(0)
        n = int(v, 0)
        return str(n) if n < 0 else '0x%04x' % n

    def fill(l):
        l = re.sub(r'\bv\d+\b', lambda m: ops.get(m.group(0), m.group(0)), l)
        return SYM.sub(value, l)
    return [fill(l) for l in rule['before']], [fill(l) for l in rule['after']]


def addresses(lines, regs):
    """The address each memory operand starts at, with the registers as they
    were at the start, and the register it is based on."""
    def r16(hi, lo):
        return int(regs.get(hi, '0'), 16) << 8 | int(regs.get(lo, '0'), 16)
    base = {'hl': lambda: r16('H', 'L'), 'de': lambda: r16('D', 'E'),
            'bc': lambda: r16('B', 'C'),
            'ix': lambda: int(regs.get('IX', '0'), 16),
            'iy': lambda: int(regs.get('IY', '0'), 16)}
    out = {}
    for l in lines:
        for op in re.findall(r'(-?\w+ \((?:ix|iy)\)|\((?:hl|de|bc)[+-]?\)|'
                             r'\(0x[0-9a-f]+(?: *[-+] *-?\w+)?\))', l):
            m = re.fullmatch(r'(-?\w+) \((ix|iy)\)', op)
            if m:
                out[op] = ((base[m.group(2)]() + int(m.group(1), 0)) & 0xFFFF,
                           m.group(2))
                continue
            m = re.fullmatch(r'\((hl|de|bc)[+-]?\)', op)
            if m:
                out[op] = (base[m.group(1)](), m.group(1))
                continue
            m = re.fullmatch(r'\((0x[0-9a-f]+)(?: *([-+]) *(-?\w+))?\)', op)
            if m:
                v = int(m.group(1), 16)
                if m.group(2):
                    v += int(m.group(3), 0) * (1 if m.group(2) == '+' else -1)
                out[op] = (v & 0xFFFF, None)
    return out


def tags(rule, case):
    """Why a counterexample may be one SDCC's code never meets."""
    regs = fields(case.get('from', ''))
    sp = int(regs.get('SP', '0'), 16)
    before, after = case_code(rule, case)
    code = before + after
    out = set()
    stack = any(l.split()[0] in STACK_OPS or re.match(r'(inc|dec)\s+sp', l)
                for l in code if not l.endswith(':'))
    if stack and any(((a - sp) & 0xFFFF) >= 0xFFE0 or
                     ((a - sp) & 0xFFFF) < 0x20
                     for a, _ in addresses(code, regs).values()):
        out.add('near SP')
    # Operands based on the same register are related on purpose, such as
    # the two bytes of a 16-bit access.
    for side in (before, after):
        vals = list(addresses(side, regs).values())
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                (a, ra), (b, rb) = vals[i], vals[j]
                if ra != rb and abs(a - b) <= 1:
                    out.add('operands overlap')
    return out


def failing(out, cpu, flags=True):
    """The failing rules, with their text and results."""
    path = os.path.join(out, f'{cpu}{"" if flags else "-noflags"}.rules')
    rules = load_rules(path)
    res = load_results(path[:-6] + '.txt')
    return OrderedDict((name, (rule, res.get(name)))
                       for name, rule in rules.items()
                       if name not in res or not res[name]['ok'])


def summary(out, cpu):
    noflags = failing(out, cpu, flags=False)
    copies = load_rules(os.path.join(out, f'{cpu}-noflags.rules'))
    for name, (rule, r) in failing(out, cpu).items():
        if r is None:
            print(f'{name}: no result')
            continue
        if r['unproven'] and not r['failed']:
            why = r['shown'][0].get('reason', '') if r['shown'] else ''
            print(f'{name}: {r["unproven"]}/{r["cases"]} not proved: '
                  f'{re.sub(r"^\S+:\d+: ", "", why)}')
            continue
        if not r['failed']:
            print(f'{name}: {r["note"]}')
            continue
        # The counterexamples of both files, as the one with the flags may
        # stop at its first.
        nf = noflags.get(name)
        shown = [c for c in r['shown'] if 'Alive2:' in c]
        if nf and nf[1]:
            shown += [c for c in nf[1]['shown'] if 'Alive2:' in c]
        diffs, tagc = Counter(), Counter()
        for case in [c for c in r['shown'] if 'Alive2:' in c]:
            b, a = fields(case.get('before', '')), fields(case.get('after', ''))
            d = {('memory' if k.startswith('(') else k)
                 for k in set(b) | set(a) if b.get(k) != a.get(k)}
            lb = re.search(r'leaves to (\S+)', case.get('before', ''))
            la = re.search(r'leaves to (\S+)', case.get('after', ''))
            if (lb and lb.group(1)) != (la and la.group(1)):
                d.add('exit')
            diffs.update(d)
        for case in shown:
            tagc.update(tags(rule, case))
        least = 'at least ' if r['least'] else ''
        parts = [f'{name}: {least}{r["failed"]}/{r["cases"]} fail']
        if diffs:
            parts.append('differ ' + ' '.join(
                f'{k}:{v}' for k, v in sorted(diffs.items())))
        if r['unproven']:
            parts.append(f'{r["unproven"]} not proved')
        if tagc:
            parts.append(' '.join(f'{k}:{v}' for k, v in sorted(tagc.items()))
                         + f' of {len(shown)} shown')
        if nf is None and name in copies:
            parts.append('without flags: 0 fail')
        elif nf and nf[1] and nf[1]['failed']:
            parts.append(f'without flags: {nf[1]["failed"]}/'
                         f'{nf[1]["cases"]} fail')
        print('; '.join(parts))


def show(out, cpu, sdcc, wanted):
    defs = {}
    for name in ('peeph.def', 'peeph-z80.def', 'peeph-sm83.def'):
        for r in peeph.load(os.path.join(sdcc, 'src', 'z80', name)):
            defs[f'{name[:-4]}-{r.line}'] = r
    noflags = failing(out, cpu, flags=False)
    for name, (rule, res) in failing(out, cpu).items():
        if wanted and name not in wanted:
            continue
        r = defs.get(name)
        nf = noflags.get(name)
        nf_res = nf[1] if nf else None
        if res:
            least = 'at least ' if res['least'] else ''
            print(f'### {name}: {least}{res["failed"]} of {res["cases"]} '
                  f'cases fail, {nf_res["failed"] if nf_res else 0} without '
                  'flags')
        else:
            print(f'### {name}: no result')
        if r:
            if r.note:
                print(f'; {r.note}')
            print('replace {\n' + ''.join(f'\t{l}\n' for l in r.before) +
                  '} by {\n' + ''.join(f'\t{l}\n' for l in r.after) + '}' +
                  (f' if {r.cond_text}' if r.cond_text else ''))
        print('\n'.join(rule['text']))
        for title, x in (('first counterexample', res),
                         ('first counterexample without flags', nf_res)):
            if not x:
                continue
            if not x['shown']:
                if x['note']:
                    print(x['note'])
                continue
            case = x['shown'][0]
            print(f'{title}:')
            for k in ('case', 'Alive2:', 'from', 'memory', 'number',
                      'before', 'after'):
                if k in case:
                    print(f'  {k:<7} {case[k]}')
        print()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('mode', choices=['summary', 'show'])
    ap.add_argument('cpu', choices=['z80', 'sm83'])
    ap.add_argument('rules', nargs='*', help='rules to show, such as '
                    'peeph-1547 (default: every failing rule)')
    ap.add_argument('--out', default=os.path.join(REPO, 'rules'),
                    help='directory with the rule files and results '
                    '(default: rules)')
    ap.add_argument('--sdcc', default=os.path.join(REPO, 'sdcc'),
                    help='SDCC source tree (default: the submodule)')
    args = ap.parse_args()
    if args.mode == 'summary':
        summary(args.out, args.cpu)
    else:
        show(args.out, args.cpu, args.sdcc, set(args.rules))


if __name__ == '__main__':
    main()
