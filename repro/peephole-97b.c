/* SDCC peephole 97b (src/z80/peeph.def) reuses a register pair that holds a
   16-bit constant to store a byte through HL, but finds the pair's high byte
   by dividing by 0xff instead of 0x100.

     sdcc -mz80 -S peephole-97b.c

   f() and g() store a byte that differs from the one the C code stores. */

void h(unsigned int a, unsigned int b);

void f(unsigned char *p)
{
    *p = 1;         /* ld de, #0x00ff / ld (hl), d: stores 0 */
    h(0, 0x00ff);
}

void g(unsigned char *p)
{
    *p = 2;         /* ld de, #0x01ff / ld (hl), d: stores 1 */
    h(0, 0x01ff);
}

void ok(unsigned char *p)
{
    *p = 0x12;      /* ld de, #0x1234 / ld (hl), d: right */
    h(0, 0x1234);
}
