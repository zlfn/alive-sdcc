# alive-sdcc

Checks SDCC's Z80 and SM83 peephole rules (`src/z80/peeph*.def`) with
[Alive2](https://github.com/AliveToolkit/alive2). Each rule is turned into a
rule of `z80-test` from [z80-lift](https://github.com/llvm-z80/z80-lift),
which proves that the replacement leaves the same registers, flags and memory
as the original for every starting state, every operand the rule applies to
and every value of its numbers.

See [FINDINGS.md](FINDINGS.md) for the results and [reports/](reports/) for
problems written up for SDCC's bug tracker, with reproductions in `repro/`.

## How it works

`convert.py` turns each SDCC rule into one z80-test rule. A pattern variable
that SDCC can only bind to a number (an immediate, an offset, an address)
becomes a number, which the proof covers for every value. Any other becomes a
variable over the operands it can stand for where it appears: the registers,
`(hl)`, `(bc)`, `(de)`, an immediate `#n`, an address `(n)`, and also `ix`,
`iy`, `n (ix)` and `n (iy)` on the Z80 or `(hl+)` and `(hl-)` on the SM83, or
the condition codes, bit numbers or opcodes it is limited to. z80-test proves
the rule for every choice of operands that meets the conditions and
assembles.

The conditions become conditions of the rule, with SDCC's own predicates,
such as `canAssign` and `operandsNotRelated`, spelled out over the operands
as `src/SDCCpeeph.c` and `src/z80/peep.c` evaluate them. Registers and flags
named by `notUsed` are not compared. Jumps out of a rule go to fixed stub
addresses, so the exit is compared too.

Each rule file also has a copy without the flags, `<cpu>-noflags.rules`, so
that a difference in a flag does not hide one in a register or in memory.

A counterexample may be a state SDCC's code never reaches, such as a pointer
into the stack slots a rule pushes to; `report.py` tags these as `near SP` or
`operands overlap`. The rules assume that SDCC's code never loads a register
from itself. Conditions a proof cannot see (`notVolatile`, label counts) are
ignored, and bits 3 and 5 of F are not modelled on the Z80. Cases with I/O
instructions or loops cannot be proved, and are counted as not proved.

## Running

Requires `z80-test` from z80-lift and Python 3.

```bash
git clone --recurse-submodules https://github.com/zlfn/alive-sdcc.git
```

`rules/` holds the rule files of the last run, so the next two steps can
also start from it.

```bash
tools/convert.py
```

```bash
Z80_TEST=/path/to/z80-test tools/run.sh
```

```bash
tools/report.py summary z80
```

```bash
tools/report.py show sm83 peeph-sm83-340
```

`convert.py` writes `rules/<cpu>.rules`, the same without flags, and
`rules/<cpu>-skipped.txt` with the rules it could not convert. `run.sh`
proves one rule at a time, `JOBS` at once (default: one per CPU), and writes
what z80-test says next to each file, with up to 20 failing cases of each
rule. A rule that has a copy without the flags stops at its first
counterexample, since the copy shows the rest. `summary` prints one line per
failing rule; `show` prints the rule, as SDCC and as `convert.py` write it,
and its first counterexample. Rules are named after their file and line:
`peeph-sm83-340` is `peeph-sm83.def:340`. `results/` holds both for the last
run, from SDCC trunk r16969.

## License

[MIT](LICENSE). Rule text and code quoted from SDCC remain under SDCC's
license (GPL-2.0-or-later).
