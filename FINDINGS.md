# Findings

Results for SDCC trunk r16969. Rules are named by their file and the line
where `replace` starts, as in `peeph.def:1547`, and by the number in their
comment, as in 97b. Rules in `peeph.def` apply to both CPUs. Each number in
a rule, such as an immediate, an offset or an address, is a symbol that the
proof covers for every value it can have, and each other pattern variable
takes every operand it can stand for in turn, so a rule that holds is proved
for all of them. See [README.md](README.md) for how the rules were checked.

| | Z80 | SM83 |
| --- | --- | --- |
| Rules checked | 290 | 252 |
| Rules proved | 202 | 180 |
| Rules with a counterexample | 84 | 68 |
| Of those, rules that fail only for flags | 40 | 30 |
| Rules with cases that cannot be proved | 4 | 4 |
| Rules not checked | 14 | 99 |

Most failing rules fall into the last sections: flags that the conditions do
not check, and counterexamples that SDCC's code does not reach.

## Wrong code from C

| Rule | Location | Problem | Report |
| --- | --- | --- | --- |
| 97b | `peeph.def:1547` | Stores the wrong byte of a 16-bit constant: it divides by `0xff` where it means `0x100` | [peephole-97b.md](reports/peephole-97b.md) |

The reproduction is for the Z80.

## Wrong rewrites in the rule text

These rules rewrite code into something that does not do the same thing, for
operands the rule was written for. I have not found C code that leads to
them.

| Rule | Location | CPU | Problem | Report |
| --- | --- | --- | --- | --- |
| 195-1, 195-2 | `peeph.def:3020`, `3028` | Z80, SM83 | Delete a jump or call that is always taken | [peephole-195.md](reports/peephole-195.md) |
| SM83 10b, 10c | `peeph-sm83.def:166`, `179` | SM83 | Replace any stack offset with 1 | [sm83-peephole-10b-10c.md](reports/sm83-peephole-10b-10c.md) |
| SM83 19 | `peeph-sm83.def:340` | SM83 | Leaves A unchanged where the original loads `0xc0` | [sm83-peephole-19.md](reports/sm83-peephole-19.md) |
| 65 | `peeph.def:951` | Z80 | The pattern stores through `(iy)`, but the replacement stores through `%4` plus SP; the pattern should use `%5 (%4)` and `%6 (%4)`, or the rule should require `same(%4 'iy')` | [peephole-65.md](reports/peephole-65.md) |
| 41a | `peeph.def:578` | Z80, SM83 | `ld (nn), de` or `ld (nn), sp` followed by `ld (nn), a` loses the store of the high byte; the rule needs both stores to have the same size | [peephole-41a.md](reports/peephole-41a.md) |
| 148 | `peeph.def:2496` | Z80 | `%4` is `a`: the pattern stores the A that `pop af` loads, and the replacement the A from before it. The condition `notSame(%3 'a')` compares the offset with `'a'`, and was probably meant to be `notSame(%4 'a')` | [peephole-148.md](reports/peephole-148.md) |
| 191c | `peeph.def:2940` | Z80, SM83 | `same(%2 'h' 'l' 'sp')` lets `inc sp / ld (nn), sp` through, which then stores SP instead of SP + 1 | [peephole-191c.md](reports/peephole-191c.md) |

The SM83 also has `ld (nn), sp`, but the llvm-mc of llvm-z80 does not
assemble it for the SM83, so 41a and 191c were only checked for the Z80.

## Missing conditions

These rules are right for the operands they are meant for, but their
conditions also let through operands that they get wrong. Most of these
operands are ones SDCC does not seem to emit in these places. None has been
reproduced from C.

| Rule | Location | CPU | Wrong when | Example |
| --- | --- | --- | --- | --- |
| 0b | `peeph.def:27` | SM83 | `%3` is memory that can be `%1`, which `operandsNotRelated` misses; `%1` is `(hl)` and `%2` is `h` or `l`; or `%4` is `(hl+)` or `(hl-)`, which changes `%1` or `%2` | `ld e, (hl) / ld (0xff80), a / ld (hl), e`, `ld e, l / ld a, (hl+) / ld l, e` |
| 10 | `peeph.def:171` | Z80, SM83 | `%1` is `h` or `l` and `%5` is `(hl)`, so the replacement stores through the old HL; needs `operandsNotRelated(%1 %5)`. Also `%3` is memory that can be `%5`, which `operandsNotRelated` misses | `ld l, d / ld a, b / ld (hl), l`, `ld c, h / ld (0x1234), a / ld (hl), c` |
| 11 | `peeph.def:183` | Z80 | `%3` and `%4` are the same offset, so the second store replaces the first; needs `notSame(%3 %4)` | `ld 1 (ix), #0x80 / ld 1 (ix), e / ld l, 1 (ix) / ld h, 1 (ix)` |
| 15 | `peeph.def:223` | Z80 | `%4` overlaps `%1`; needs `operandsNotRelated(%1 %4)`. In this case the first load is dead, and rule 7 removes it first | `ld e, 0 (iy) / ld de, #0 / ld h, e` |
| 36 | `peeph.def:499` | Z80, SM83 | `%1` is `%2` or `hl`; needs `notSame(%1 %2 'hl')` | `pop de / pop de / push de / push de / ld a, #0xff / ld (de), a` |
| 39 | `peeph.def:552` | Z80, SM83 | `%2` is `hl`; also `add hl` sets H and C, and `inc hl` does not. Needs `notSame(%2 'hl')` and `notUsed('hf' 'cf')` | `ld hl, #1 / add hl, hl` |
| 51a | `peeph.def:765` | Z80, SM83 | `%2` is `sp`; needs `notSame(%2 'sp')` | `pop de / ld sp, hl / push de` |
| 59 | `peeph.def:882` | Z80 | `%3` is `h` or `l`, which the replacement has changed before the store; needs `notSame(%3 'h' 'l')` | `ld ix, #0xff / ld 1 (ix), h / ld l, 1 (ix)` |
| 99a | `peeph.def:1594` | Z80, SM83 | `%1` is `h`, `l` or `a` | `ld l, (hl) / inc hl / ld a, (hl) / or a, l` |
| 104 | `peeph.def:1726` | Z80, SM83 | The second load changes an operand of the first, so loading back is not redundant | `ld (hl), e / ld e, b / ld e, (hl) / ld b, e` |
| 104b | `peeph.def:1737` | Z80, SM83 | One of `%1` and `%2` is `(hl)` and the other `h` or `l` | `ld h, (hl) / dec h / ld (hl), h` |
| 115 | `peeph.def:1879` | Z80, SM83 | `%1` is `h` or `l`; needs `notSame(%1 'h' 'l')` | `ld l, (hl) / inc l / ld (hl), l` |
| 115a | `peeph.def:1888` | Z80, SM83 | `%1` is `h` or `l`, `%2` is `%1` or reads through it, or `%2` is `(hl+)` or `(hl-)` | `ld b, (hl) / ld a, b / add a, b` |
| 120 | `peeph.def:1952` | Z80, SM83 | `%2` is `hl`; also H and C come from a different sum. Needs `notSame(%2 'hl')` and `notUsed('hf' 'cf')` | `ld hl, #1 / add hl, hl / ld bc, #2 / add hl, bc` |
| 129a to 129d | `peeph.def:2168`, `2179`, `2189`, `2199` | Z80, SM83 | The same as 120 | `ld hl, #0xff / add hl, hl / inc hl` |
| 137 | `peeph.def:2338` | Z80, SM83 | `%3` is memory that can be `%1`, which `operandsNotRelated` misses | `ld (hl), #2 / ld (de), a / ld (hl), #2` |
| 141 | `peeph.def:2415` | Z80 | The same as 120 | `ld hl, #1 / add hl, hl / ex de, hl / inc de` |
| 151 | `peeph.def:2527` | SM83 | `%1` is `(hl+)` or `(hl-)`; needs `notSame(%1 '(hl+)' '(hl-)')` as other rules have | `ld (hl+), a / or a, a / jp z, L / ld a, (hl+)` |
| 176a | `peeph.def:2844` | Z80, SM83 | `%1` is `h` or `l` and `%2` is `(hl)`, so the store back goes through the new HL; needs `operandsNotRelated(%1 %2)` | `ld h, (hl) / ld (hl), h` |
| 194-1, 194-2 | `peeph.def:2975`, `2997` | SM83 | An operand is `(hl+)` or `(hl-)`: the replacement reads the bytes in another order, so it reads other addresses and leaves HL elsewhere. `canAssign('b' %3)` only rules this out for `%3` | `ld a, (hl-) / sub a, #2 / ld a, (hl) / sbc a, #0 / ld a, #0xff / sbc a, #0 / ld a, c / sbc a, #0 / jp c, L` |
| SM83 2b, 3 | `peeph-sm83.def:59`, `68` | SM83 | `%1` is `h` or `l`; needs `notSame(%1 'h' 'l')` | `ld l, (hl) / inc hl` |
| SM83 10a | `peeph-sm83.def:155` | SM83 | `%2` is `h`, `l` or `sp`, or `%3` is `(hl-)`. The condition `notSame('(hl+)' %2 %3)` appears twice, and the second was probably meant to be `notSame('(hl-)' %2 %3)` | `ldhl sp, #2 / ld h, c / ldhl sp, #2` |

## Flags that the conditions do not check

These rules change flags that their conditions do not require to be unused
afterwards, and hold when the flags are left out, except 67b. Only `daa`
reads H and N, so a rule that changes only those is unlikely to matter. A
counterexample shows one starting state, so other flags than those listed may
differ as well.

| Rule | Location | CPU | Flags seen to differ | `notUsed` conditions |
| --- | --- | --- | --- | --- |
| 2b | `peeph.def:49` | Z80, SM83 | H | `notUsed('hl' 'cf' 'nf')` |
| 2d | `peeph.def:61` | SM83 | Z | `notUsed('a' 'hf' 'nf' 'cf')` |
| 3a | `peeph.def:74` | Z80 | S | `notUsed('l' 'zf')` |
| 3b | `peeph.def:83` | Z80 | S | `notUsed('l' 'zf')` |
| 9c | `peeph.def:162` | Z80, SM83 | N | `notUsed('hf')`, `notUsed('cf')` |
| 22 | `peeph.def:283` | Z80 | Z P/V | `notUsed(%1)` |
| 62 | `peeph.def:911` | Z80 | H | `notUsed(%4 'hl')` |
| 63 | `peeph.def:925` | Z80 | H | `notUsed(%4 'hl')` |
| 64 | `peeph.def:936` | Z80 | H | `notUsed(%4 'a')` |
| 67a | `peeph.def:993` | Z80 | H C | `notUsed(%4 'hl')` |
| 67b | `peeph.def:1004` | Z80 | S Z H C, and A | `notUsed(%4 'hl')` |
| 67c | `peeph.def:1015` | Z80, SM83 | H | `notUsed('a')` |
| 86 | `peeph.def:1245` | Z80, SM83 | Z H P/V | none |
| 89 | `peeph.def:1278` | Z80, SM83 | H | none |
| 90a | `peeph.def:1287` | Z80, SM83 | S Z H | `notUsed('a')` |
| 90b | `peeph.def:1297` | Z80, SM83 | S Z H | `notUsed('a')` |
| 92b | `peeph.def:1315` | Z80, SM83 | H P/V | `notUsed('a' 'cf' 'zf')` |
| 92c | `peeph.def:1324` | Z80, SM83 | H P/V | `notUsed('a' 'cf' 'zf')` |
| 93b | `peeph.def:1341` | Z80, SM83 | H P/V | `notUsed('a' 'cf' 'zf')` |
| 93c | `peeph.def:1350` | Z80, SM83 | H P/V | `notUsed('a' 'cf' 'zf')` |
| 100 | `peeph.def:1622` | Z80, SM83 | H | none |
| 100a | `peeph.def:1630` | Z80 | H | none |
| 102a | `peeph.def:1665` | Z80, SM83 | H P/V N | `notUsed('cf')` |
| 102b | `peeph.def:1673` | Z80, SM83 | H P/V N | `notUsed('cf')` |
| 102c | `peeph.def:1684` | Z80 | P/V N | `notUsed('a')` |
| 102d | `peeph.def:1695` | Z80, SM83 | P/V N | none |
| 109 | `peeph.def:1799` | Z80, SM83 | S Z H | none |
| 112 | `peeph.def:1832` | Z80, SM83 | Z | `notUsed('hl')` |
| 113 | `peeph.def:1848` | Z80, SM83 | Z | `notUsed('hl')` |
| 115b | `peeph.def:1898` | Z80, SM83 | S Z H P/V C | `notUsed(%1)` |
| 133 | `peeph.def:2303` | Z80, SM83 | S Z H P/V N C | `notUsed('a')` |
| 139 | `peeph.def:2358` | Z80, SM83 | N | none |
| 150 | `peeph.def:2517` | Z80 | H P/V N | none |
| 155c | `peeph.def:2602` | Z80, SM83 | H N | `notUsed('cf')` |
| 156a | `peeph.def:2609` | Z80, SM83 | N | none |
| 192 | `peeph.def:2949` | Z80, SM83 | H C | `notUsed(%3)` |
| 193 | `peeph.def:2961` | Z80, SM83 | C | `notUsed('hl')` |
| 194-1 | `peeph.def:2975` | Z80 | Z P/V N | `notUsed('a')` |
| 194-2 | `peeph.def:2997` | Z80 | S Z P/V N | `notUsed('a')` |
| 157d | `peeph.def:3087` | Z80 | Z N | none |
| 167 | `peeph.def:3186` | Z80 | S H N | none |
| Z80 178 | `peeph-z80.def:22` | Z80 | Z P/V | `notUsed('a')` |
| SM83 10d | `peeph-sm83.def:192` | SM83 | H | none |
| SM83 10e | `peeph-sm83.def:200` | SM83 | H C | none |
| SM83 sp3 | `peeph-sm83.def:421` | SM83 | N | `notUsed('sp')` |
| SM83 sp8b | `peeph-sm83.def:451` | SM83 | H C | none |

Notes on some of them:

- 2d removes `rlca`, `rla`, `rrca` and `rra`. On the Z80 they leave Z alone,
  but on the SM83 they clear it, so the SM83 also needs `'zf'`.
- 62 to 67b fold the offset into the constant added to SP, so `add hl, sp`
  sets H and C from a different sum. 67b also allows `adc` and `sbc`, which
  then read that carry.
- 192, 193, SM83 10d, 10e, sp3 and sp8b compute SP or HL another way, which
  sets H and C differently.

## Rules that never apply

These rules can never match, because a condition is always false. They are
not wrong, but they do nothing.

| Rule | Location | Condition that is always false |
| --- | --- | --- |
| 30 | `peeph.def:426` | `canJoinRegs(%3 %2 %5)` cannot bind `%5` again, since the pattern has bound it to a single register, so `same(%5 %4)` compares a register with a register pair |
| 45, 46 | `peeph.def:640`, `647` | `canAssign(%3 %4)`: `immdInRange` binds `%4` to a bare number, and `z80canAssign` only takes immediates that start with `#` |

## Counterexamples that SDCC's code does not reach

In these rules, every failing case has a memory operand that points into
the stack slots the code pushes or pops, or below SP, apart from the `pop af`
cases below. SDCC's code does not access the stack that way. `report.py` tags
them `near SP`.

| Rule | Location |
| --- | --- |
| 34 | `peeph.def:476` |
| 43 | `peeph.def:598` |
| 44a, 44b | `peeph.def:610`, `624` |
| 47a, 47b, 47c | `peeph.def:654`, `668`, `686` |
| 51 | `peeph.def:756` |
| 52c | `peeph.def:791` |
| 94d | `peeph.def:1412` |
| 110 | `peeph.def:1809` |
| 177b, 177c | `peeph.def:2869`, `2878` |
| 190 | `peeph.def:2909` |
| 191b | `peeph.def:2929` |

Rules that remove `pop af` and `push af`, 50a (`peeph.def:734`), 51
(`peeph.def:756`), 51a (`peeph.def:765`), SM83 sp1 (`peeph-sm83.def:402`) and
SM83 sp2 (`peeph-sm83.def:410`), also fail for AF alone. On the SM83, `pop af`
clears the low four bits of F, so `pop af / push af` changes the byte on the
stack, and the replacement leaves it as it was. On the Z80 they fail because
z80-lift does not model bits 3 and 5 of F. Either way the replacement keeps
the byte that was on the stack, which is what code that reads it later
expects.

## Not proved

z80-test cannot prove these rules for every case:

| Rule | Location | CPU | Why |
| --- | --- | --- | --- |
| 96b | `peeph.def:1508` | Z80 | 4 cases have `in`, which z80-lift does not model |
| 128a, 128b, 128c | `peeph.def:2090`, `2110`, `2139` | Z80, SM83 | The code has a loop |
| SM83 21 | `peeph-sm83.def:362` | SM83 | The code has a loop |

## Not checked

[rules/z80-skipped.txt](rules/z80-skipped.txt) and
[rules/sm83-skipped.txt](rules/sm83-skipped.txt) list the rules that
`convert.py` could not write and why:

- "for other ports": `isPort` leaves the CPU out.
- "has no operand on the SM83": a variable can only be an index register.
- "never holds": a condition is always false, as for 45 and 46 above, or
  `notUsed('iy')` on the SM83.
- "an assertion, not an instruction" and "is an opcode without same()":
  `convert.py` cannot write these rules.

For the others, z80-test says "no case assembles" when no choice of operands
gives code that assembles: the rule needs instructions that the CPU does not
have, such as `ex de, hl` or index registers on the SM83, or `n (sp)` on the
Z80, as for 98b; it needs a symbol, as for 3; or it never applies, as for 30.

## Problems in the peephole engine

These affect every rule that uses the condition, on all Z80 family ports.

| Where | Problem | Report |
| --- | --- | --- |
| `operandsNotRelated` in `src/SDCCpeeph.c` | Replaces the first operand of each pair by its base name before checking for two memory operands, so `(hl)`, `(de)`, `(bc)` and index operands are never seen as memory. `(hl)` and `(de)` count as unrelated. Rules 0b, 10 and 137 go wrong because of it | [operands-not-related.md](reports/operands-not-related.md) |
| `bindVar` in `src/SDCCpeeph.c` | A condition that binds a variable that is already bound keeps the old value and does not compare it with the new one. Rule 30 never applies because of it | |
| `z80canAssign` in `src/z80/peep.c` | Tests `src` in three places where it means `dst`, so it never allows `ld (hl+), a`, `ld (hl-), a`, `ld sp, #nn` or `ld sp, (nn)`. Rules that need these never apply | |

The three tests in `z80canAssign`:

```c
if((!strcmp(dst, "(bc)") || !strcmp(dst, "(de)") || !strcmp(src, "(hl+)") || !strcmp(src, "(hl-)"))
   && !strcmp(src, "a"))
...
if((isReg(dst) || isRegPair(dst) || !strcmp(src, "sp")) && src[0] == '#')
...
if((!strcmp(dst, "a") || (!IS_SM83 && (isRegPair(dst) || !strcmp(src, "sp")))) && !strncmp(src, "(#", 2))
```
