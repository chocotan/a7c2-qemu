#include <stddef.h>
#define EVP_MAX_MD_SIZE 64
typedef struct evp_cipher_ctx_st EVP_CIPHER_CTX;
typedef struct evp_cipher_st EVP_CIPHER;
typedef struct evp_md_st EVP_MD;
typedef struct evp_md_ctx_st EVP_MD_CTX;
struct engine_st;
EVP_MD_CTX *EVP_MD_CTX_new(void);
void EVP_MD_CTX_free(EVP_MD_CTX *);
int EVP_DigestInit_ex(EVP_MD_CTX *,const EVP_MD *,struct engine_st *);
int EVP_DigestUpdate(EVP_MD_CTX *,const void *,size_t);
int EVP_DigestFinal_ex(EVP_MD_CTX *,unsigned char *,unsigned int *);
typedef struct engine_st ENGINE;
EVP_CIPHER_CTX *EVP_CIPHER_CTX_new(void);
void EVP_CIPHER_CTX_free(EVP_CIPHER_CTX *);
int EVP_CIPHER_CTX_set_padding(EVP_CIPHER_CTX *,int);
const EVP_CIPHER *EVP_aes_256_cbc(void);
int EVP_DecryptInit_ex(EVP_CIPHER_CTX *,const EVP_CIPHER *,ENGINE *,const unsigned char *,const unsigned char *);
int EVP_DecryptUpdate(EVP_CIPHER_CTX *,unsigned char *,int *,const unsigned char *,int);
int EVP_DecryptFinal_ex(EVP_CIPHER_CTX *,unsigned char *,int *);
const EVP_MD *EVP_sha256(void);
int EVP_Digest(const void *,size_t,unsigned char *,unsigned int *,const EVP_MD *,ENGINE *);
