"""Reads SDCC peephole definition files."""

import re
from dataclasses import dataclass, field


@dataclass
class Rule:
    file: str
    line: int
    before: list
    after: list
    conds: list = field(default_factory=list)  # (name, [args])
    cond_text: str = ''  # the conditions as the file writes them
    note: str = ''  # the comment in the replacement, naming the rule


def split_args(text):
    """Arguments of a condition: %N, quoted strings or bare words."""
    return re.findall(r"%x?\d+|'[^']*'|[^\s,']+", text)


def parse_conds(text):
    """Conditions as (name, args), reading quoted arguments whole: '(hl)'
    holds a parenthesis."""
    conds = []
    i = 0
    while True:
        m = re.compile(r'(\w+)\s*\(').search(text, i)
        if not m:
            return conds
        j, depth, quote = m.end(), 1, False
        while depth:
            ch = text[j]
            if ch == "'":
                quote = not quote
            elif not quote:
                depth += {'(': 1, ')': -1}.get(ch, 0)
            j += 1
        args = text[m.end():j - 1]
        conds.append((m.group(1), [a[1:-1] if a.startswith("'") else a
                                   for a in split_args(args)]))
        i = j


def load(path):
    text = open(path).read()
    rules = []
    lines = text.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i].split('//')[0].strip()
        if not line.startswith('replace'):
            i += 1
            continue
        start = i + 1
        # The pattern, up to "} by {".
        body = []
        i += 1
        while not re.match(r'\s*}\s*by\s*{', lines[i]):
            body.append(lines[i])
            i += 1
        repl = []
        i += 1
        while not lines[i].strip().startswith('}'):
            repl.append(lines[i])
            i += 1
        tail = lines[i].strip()[1:]
        # Conditions may continue on the following lines after a comma.
        while tail.rstrip().endswith(',') and i + 1 < len(lines) and \
                lines[i + 1].strip() and not lines[i + 1].strip().startswith(('replace', '//')):
            i += 1
            tail += ' ' + lines[i].strip()
        i += 1
        clean = lambda ls: [l.split(';')[0].strip() for l in ls
                            if l.split(';')[0].strip() not in ('', '{')]
        note = ' '.join(l.split(';', 1)[1].strip() for l in repl if ';' in l)
        conds, cond_text = [], ''
        m = re.match(r'\s*if\s+(.*)', tail)
        if m:
            cond_text = ' '.join(m.group(1).split()).rstrip(', ')
            conds = parse_conds(cond_text)
        rules.append(Rule(path, start, clean(body), clean(repl), conds,
                          cond_text, note))
    return rules
