# Peephole 191c moves a store of SP past inc sp

Common peephole 191c (`src/z80/peeph.def`) moves a store of H or L before an
`inc sp`:

```
replace restart {
	inc	sp
	ld	%1, %2
} by {
	; common peephole 191c: move register store before stack restore
	ld	%1, %2
	inc	sp
} if notUsed('hl'), same(%2 'h' 'l' 'sp'), notSame(%1 'h' 'l' 'sp')
```

`same(%2 'h' 'l' 'sp')` also lets `%2` be `sp`. SP is the one register that
`inc sp` changes, so the store then writes a different value:

```
	inc	sp
	ld	(_x), sp        ; stores SP + 1
```

becomes

```
	ld	(_x), sp        ; stores SP
	inc	sp
```

`ld (nn), sp` exists on both the Z80 and the SM83. Removing `'sp'` from the
`same()` condition fixes the rule.

I have not found C code that leads to this.
