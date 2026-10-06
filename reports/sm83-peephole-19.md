# SM83 peephole 19 leaves A unchanged

SM83 peephole 19 (`src/z80/peeph-sm83.def`) pushes the byte in A and the
constant `0xc0` with one `push af`, using `cp a` to set F to `0xc0`:

```
replace {
	push	af
	inc	sp
	ld	a, #%2
	push	af
	inc	sp
} by {
	; sm83 peephole 19 pushed #%2 via flags
	cp	a
	push	af
} if operandsLiteral(%2), immdInRange(0xC0 0xC0 '+' %2 0 %x3), notUsed('f')
```

The stack and SP end up the same, but the original code leaves `0xc0` in A
and the replacement leaves A as it was. The rule checks that F is not used
afterwards, but not A. It needs `notUsed('a' 'f')`.

## Counterexample

```
	push	af
	inc	sp
	ld	a, #0xc0
	push	af
	inc	sp
	ld	(hl), a         ; stores 0xc0
```

becomes

```
	cp	a
	push	af
	ld	(hl), a         ; stores the byte that was pushed first
```

In the cases I tried, such as `h(0xc0, 0, 0xc0, x)` for
`void h(unsigned char, unsigned char, unsigned char, unsigned char)`, the rule
fires and SDCC then loads A again for the register argument, so I have not
found C code that goes wrong.

The other rules of this kind, 18a to 18g, set F to the value they push and
are correct.
