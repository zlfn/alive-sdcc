# SM83 peepholes 10b and 10c replace any stack offset with 1

SM83 peepholes 10b and 10c (`src/z80/peeph-sm83.def`) turn the second of two
`ldhl sp` one byte apart into `dec hl` or `inc hl`, but their replacement also
rewrites the first `ldhl` to a fixed offset of 1:

```
replace restart {
	ldhl	sp,	#%1
	ld	%3, %4
	ld	%5, %6
	ldhl	sp,	#%2
} by {
	ldhl	sp,	#1
	ld	%3, %4
	ld	%5, %6
	; sm83 peephole 10b turned ldhl into dec hl
	dec	hl
} if operandsLiteral(%1 %2), notSame('l' %3 %5), notSame('l' %3 %5), immdInRange(0x01 0x01 '-' %1 %2 %3), operandsNotRelated('hl' %3 %4 %5 %6)
```

and the same with `inc hl` for 10c, where `%2 - %1` is 1. The result is only
right when `%1` is 1. For any other offset, HL ends up at the wrong stack
slot:

```
	ldhl	sp, #5
	ld	b, a
	ld	c, a
	ldhl	sp, #4          ; HL = SP + 4
```

becomes

```
	ldhl	sp, #1
	ld	b, a
	ld	c, a
	dec	hl              ; HL = SP + 0
```

The first line of the replacement should be `ldhl sp, #%1`.

Two smaller points about the same rules:

- `ldhl sp, #e` sets H and C, and `inc hl` / `dec hl` leave the flags alone,
  so the rules also need `notUsed('hf' 'cf')`, or `notUsed('f')`.
- `immdInRange(0x01 0x01 '-' %1 %2 %3)` names `%3`, which the pattern has
  already bound to the destination of the first `ld`. `bindVar` keeps the
  first binding, so the condition works as a check, but a variable of its own
  (`%7`) would say what is meant.

I have not found C code that makes SDCC emit these sequences.
