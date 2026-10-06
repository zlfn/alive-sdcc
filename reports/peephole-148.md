# Peephole 148 checks the offset where it means the stored register

Common peephole 148 (`src/z80/peeph.def`) replaces a store through IX or IY,
loaded with an address just for it, by a store to that address through A:

```
replace restart {
	pop	af
	ld	%1,#%2
	ld	%3 (%1),%4
	ld	%1,#%5
} by {
	ld	a,%4
	ld	(#%2 + %3),a
	; common peephole 148 used #%2 directly instead of going through %1 using indirect addressing.
	pop	af
	ld	%1,#%5
} if notSame(%3 'a')
```

The replacement moves the store before `pop af`. That is only right when
`%4` is not A: in the pattern the store writes the A that `pop af` loads,
and in the replacement it writes the A from before. The condition
`notSame(%3 'a')` compares the offset `%3` with `'a'`, which is never the
same, and was probably meant to be `notSame(%4 'a')`.

## Counterexample

```
	pop	af
	ld	ix, #_x
	ld	0 (ix), a       ; stores the A that pop af loads
	ld	ix, #_y
```

becomes

```
	ld	a, a
	ld	(#_x + 0), a    ; stores the A from before pop af
	pop	af
	ld	ix, #_y
```

In the cases I tried, SDCC 4.6.0 stores to globals through HL or to their
address directly rather than through IX or IY right after `pop af`, so I have
not found C code that goes wrong.
