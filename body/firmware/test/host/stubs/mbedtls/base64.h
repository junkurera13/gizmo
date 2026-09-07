#pragma once
#include <cstddef>
// Base64 is supplied by mbedTLS on target; these tests do not exercise that library.
inline int mbedtls_base64_encode(unsigned char*,size_t,size_t* n,const unsigned char*,size_t) {*n=0;return -1;}
inline int mbedtls_base64_decode(unsigned char*,size_t,size_t* n,const unsigned char*,size_t) {*n=0;return -1;}
