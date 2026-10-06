# Peephole 97b stores the wrong byte of a 16-bit constant

Common peephole 97b (`src/z80/peeph.def`) replaces a constant store through HL
followed by a 16-bit constant load with the load and a store of one of the
pair's registers:

```
replace {
	ld	(hl), #%2
	ld	%1, #%3
} by {
	; common peephole 97b reused constant loaded into register pair.
	ld	%1, #%3
	ld	(hl), %4
} if same(%1 'bc' 'de'), operandsLiteral(%2 %3), canSplitReg(%1 %4 %5), immdInRange(0x00 0xff '/' %3 0xff %6), immdInRange(0x00 0xff '&' %6 0xff %7), immdInRange(0 0 '-' %7 %2 %8)
// ., ., ., ., bit shift, get second byte, compare second byte with %2
```

`%4` is the high register of the pair, so the rule must only fire when the
high byte of `%3` equals `%2`. The first `immdInRange` is meant to shift `%3`
right by 8 bits, but it divides by `0xff` instead of `0x100`. Whenever
`%3 / 0xff` and `%3 / 0x100` differ, as for `0x00ff` (1 and 0) or `0x01ff`
(2 and 1), the rule stores the wrong byte.

## Reproduction

With SDCC 4.6.0 #16555, `sdcc -mz80 -S` on

```c
void h(unsigned int a, unsigned int b);

void f(unsigned char *p)
{
    *p = 1;
    h(0, 0x00ff);
}
```

gives

```
_f::
	ld	de, #0x00ff
	ld	(hl), d
	ld	hl, #0x0000
	jp	_h
```

which stores 0 through `p` instead of 1. With `*p = 2; h(0, 0x01ff);` it
stores 1. A test in the form of the regression tests is in
[`repro/peephole-97b-test.c`](../repro/peephole-97b-test.c).

## Fix

Divide by `0x100` in the first condition:

```
immdInRange(0x00 0xff '/' %3 0x100 %6)
```

Peephole 97a, which reuses the low register, takes the low byte with `& 0xff`
and is not affected.
