# Peephole 41a drops a 16-bit store followed by an 8-bit one

Common peephole 41a (`src/z80/peeph.def`) removes the first of two stores to
the same place:

```
replace restart {
	ld	%1, %2
	ld	%1, %3
} by {
	; common peephole 41a remove double load to %1.
	ld	%1, %3
} if notVolatile(%1), notVolatile(%2), notSame(%1 '(hl+)' '(hl-)'), notSame(%2 '(hl+)' '(hl-)'), operandsNotRelated(%1 %3)
```

This is only right if the second store writes at least as many bytes as the
first. When `%1` is an absolute address, `%2` can be a register pair and `%3`
a single register:

```
	ld	(_x), de
	ld	(_x), a
```

The first line writes `_x` and `_x + 1`, the second only `_x`. After the rule
only `ld (_x), a` is left, and `_x + 1` keeps its old value instead of D. The
same happens with `ld (_x), sp`, which the SM83 also has.

The rule needs `%2` and `%3` to have the same size, for example by adding
`notSame(%2 'bc' 'de' 'hl' 'ix' 'iy' 'sp')` and covering two 16-bit stores
in a rule of their own.

I have not found C code that leads to this. For a 16-bit store followed by a
store to its low byte, SDCC 4.6.0 writes the second store through HL
(`ld hl, #_x` and `ld (hl), c`).
