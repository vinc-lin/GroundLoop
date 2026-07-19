#include <stddef.h>

int decode_frame(const unsigned char *buf, int len) {
    int header = buf[0];      /* deref: crashes if buf is NULL */
    if (header < 0 || len <= 0) return -1;
    return header + len;
}
