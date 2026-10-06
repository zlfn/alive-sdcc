# operandsNotRelated misses two memory operands

`operandsNotRelated` in `src/SDCCpeeph.c` is meant to fail when two of its
operands might be the same or overlapping memory, but for the Z80 family it
only does so when one of them is an absolute address:

```c
  while ((op1 = setFirstItem (operands)))
    {
      deleteSetItem (&operands, (void*)op1);
      op1 = operandBaseName (op1);

      for (op2 = setFirstItem (operands); op2; op2 = setNextItem (operands))
        {
          if ((strchr(op1, '(') || strchr(op1, '[')) && (strchr(op2, '(') || strchr(op2, '['))) // Might be the same or overlapping memory locations; err on the safe side.
```

`op1` is replaced by its base name before the check. For `TARGET_Z80_LIKE`,
`operandBaseName` turns `(hl)`, `(hl+)`, `(hl-)`, `(de)`, `(bc)` and any
`n (ix)` or `n (iy)` into a register name without parentheses, so the check
never sees them as memory. `setFromConditionArgs` adds the arguments at the
head of the set, so `op1` is the later argument of each pair. As a result
`operandsNotRelated(%3 %1)` succeeds for `%1 = (hl)` and `%3 = (de)`,
`(bc)` or `(_x)`, which can all be the same byte as `(hl)`. With the
arguments the other way round, `(_x)` and `(hl)` are caught.

## Rules that go wrong because of it

Rule 137 (`peeph.def:2338`):

```
replace restart {
	ld	%1,#%2
	ld	%3,%4
	ld	%1,#%2
} by {
	ld	%1,#%2
	ld	%3,%4
	; common peephole 137 removed load of #%2 into %1 since it's still there.
} if notVolatile(%1), operandsNotRelated(%3 %1), notSame(%1 '(hl+)' '(hl-)')
```

turns

```
	ld	(hl), #0x02
	ld	(de), a
	ld	(hl), #0x02
```

into the first two lines, which leaves A in memory instead of 2 when DE
equals HL. Rule 0b (`peeph.def:27`, SM83) and rule 10 (`peeph.def:171`) can
move or remove a store past another store through a different pointer in the
same way.

I have not found C code that leads to this. For `*p = 2; *q = a; *p = 2;`
SDCC removes the first store itself or puts more than one instruction
between the stores.

## Fix

Check for memory before taking the base name:

```c
      const char *mem1 = op1;
      op1 = operandBaseName (op1);
      ...
          if ((strchr(mem1, '(') || strchr(mem1, '[')) && (strchr(op2, '(') || strchr(op2, '[')))
```

Rules 79 to 82 (`peeph.def:1172` to `1202`) pass the literals `'(hl)'`,
`'(ix)'` and `'(iy)'` to `operandsNotRelated`. With the fix they would never
apply, so they should use `notSame(%2 '(hl)' '(ix)' '(iy)')` instead.
