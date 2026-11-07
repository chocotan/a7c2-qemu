/* Exact OpenSSL 1.1.0 ABI. No observer crypto, allocation or ERR_* calls. */
int SHA1_Final(unsigned char *digest,void *context) {
    int saved=*__errno_location();
    int (*fn)(unsigned char *,void *)=dlvsym((void *)-1,"SHA1_Final","OPENSSL_1_1_0");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && tail_site(0,caller,0xaba8);
    *__errno_location()=saved;int rc=fn(digest,context),error=*__errno_location();
    if(observe) {
        unsigned char bytes[20];char hex[41]="",data[240];int re=0;long n=0;
        if(rc==1 && digest){n=passive_read(bytes,digest,20,&re);if(n==20)trust_hex(hex,bytes,20);}
        snprintf(data,sizeof data,"digest=%p context=%p digest_hex=%s actual=%ld read_errno=%d native_calls=1 error_queue=untouched",digest,context,hex,n,re);
        tail_emit(T_SIG,"SHA1_Final",data,rc,error,caller);
    }
    *__errno_location()=error;return rc;
}
unsigned char *SHA256(const void *data,size_t bytes,unsigned char *out) {
    int saved=*__errno_location();
    unsigned char *(*fn)(const void *,size_t,unsigned char *)=dlvsym((void *)-1,"SHA256","OPENSSL_1_1_0");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && tail_site(0,caller,0xadf0);
    *__errno_location()=saved;unsigned char *rc=fn(data,bytes,out);int error=*__errno_location();
    if(observe) {
        unsigned char digest[32];char hex[65]="",line[300];int re=0;long n=0;
        if(rc){n=passive_read(digest,rc,32,&re);if(n==32)trust_hex(hex,digest,32);}
        snprintf(line,sizeof line,"data=%p bytes=%lu out=%p returned=%p digest_hex=%s actual=%ld read_errno=%d native_calls=1 error_queue=untouched",data,(unsigned long)bytes,out,rc,hex,n,re);
        tail_emit(T_SIG,"SHA256",line,(long)rc,error,caller);
    }
    *__errno_location()=error;return rc;
}
int RSA_verify(int type,const unsigned char *digest,unsigned digest_length,
               const unsigned char *signature,unsigned signature_length,void *rsa) {
    int saved=*__errno_location();
    int (*fn)(int,const unsigned char *,unsigned,const unsigned char *,unsigned,void *)=
        dlvsym((void *)-1,"RSA_verify","OPENSSL_1_1_0");if(!fn)__builtin_trap();
    void *caller=__builtin_return_address(0);int observe=!trust_internal && tail_site(0,caller,0xae0c);
    *__errno_location()=saved;int rc=fn(type,digest,digest_length,signature,signature_length,rsa),error=*__errno_location();
    if(observe) {
        char line[360];snprintf(line,sizeof line,"type=%d digest=%p digest_length=%u signature=%p signature_length=%u rsa=%p args=6 native_calls=1 error_queue=untouched opaque_dereferenced=0",type,digest,digest_length,signature,signature_length,rsa);
        tail_emit(T_SIG,"RSA_verify",line,rc,error,caller);
    }
    *__errno_location()=error;return rc;
}
