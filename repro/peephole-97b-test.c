/** peephole 97b takes the wrong byte of a 16-bit constant.
 */
#include <testfwk.h>

unsigned int seen;

void h(unsigned int a, unsigned int b)
{
  (void)a;
  seen = b;
}

void f(unsigned char *p)
{
  *p = 1;
  h(0, 0x00ff);
}

void testPeephole97b(void)
{
  unsigned char c = 0x55;
  f(&c);
  ASSERT(c == 1);
  ASSERT(seen == 0x00ff);
}
