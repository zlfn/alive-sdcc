# Peephole 65 matches stores through IY for any register

Common peephole 65 (`src/z80/peeph.def`) replaces an address computed in
`%4` from SP, followed by two stores, with the same through HL:

```
replace restart {
	ld	%4, #%1
	add	%4, sp
	ld	%5 (iy), #%2
	ld	%6 (iy), #%3
} by {
	; common peephole 65 used hl instead of %4.
	ld	hl, #%1 + %5
	add	hl, sp
	ld	(hl), #%2
	inc	hl
	ld	(hl), #%3
} if immdInRange(-128 127 '+' %5 1 %7), same(%7 %6), notUsed(%4 'hl')
```

The stores in the pattern use `(iy)` where the neighbouring rules 62, 63 and
64 use `(%4)`. Nothing ties `%4` to IY, so the rule also matches when `%4` is
`ix` or `hl`, and then stores at SP + `%1` + `%5` instead of at IY + `%5`:

```
	ld	ix, #2
	add	ix, sp
	ld	-2 (iy), #0x01
	ld	-1 (iy), #0x02
```

becomes

```
	ld	hl, #2 + -2
	add	hl, sp
	ld	(hl), #0x01
	inc	hl
	ld	(hl), #0x02
```

The pattern should use `%5 (%4)` and `%6 (%4)`, or the rule should require
`same(%4 'iy')`.

Since the rule requires `%4` to be unused afterwards, the wrong case needs an
address computed in IX or HL that is never used, so it is unlikely to come up
in SDCC's code.
