# Peepholes 195-1 and 195-2 delete a jump that is always taken

Common peepholes 195-1 and 195-2 (`src/z80/peeph.def`) remove a comparison
against `0xff` (or `0xffff`) together with the conditional jump or call that
follows it:

```
replace restart {
	ld	a, #0xff
	cp	a, %1
	%2	nc, %3
} by {
	; common peephole 195-1: remove always true check
} if same(%2 'jr' 'jp' 'call'), notUsed('a'), labelRefCountChange(%3 -1)

replace restart {
	ld	a, #0xff
	sub	a, %1
	ld	a, #0xff
	sbc	a, %2
	%3	nc, %4
} by {
	; common peephole 195-2: remove always true check
} if same(%3 'jr' 'jp' 'call'), notUsed('a'), labelRefCountChange(%4 -1)
```

`0xff - x` never borrows, so carry is always clear after the `cp` (or the
`sub` / `sbc` pair), and the `nc` jump or call is always taken. Removing it
makes control fall through instead. The replacement should keep the transfer
and drop only the test, that is `%2 %3` for 195-1 and `%3 %4` for 195-2
(`jp %3`, `jr %3` or `call %3`), or the rules should apply only where the
target is the next instruction.

## Counterexample

For 195-1 with `jp`:

```
	ld	a, #0xff
	cp	a, b
	jp	nc, taken
	ld	c, #1
	...
taken:
	ld	c, #2
```

runs `ld c, #2` for every value of B, and after the rule runs `ld c, #1`.

I have not found C code that makes SDCC emit these sequences: comparisons that
are always true or false are folded before code generation. The rules may
still apply to code that other peepholes produce.
