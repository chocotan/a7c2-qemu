/* Host-only whole-generated-C refusal and receiver hash/window checks; UNRUN. */
#define _GNU_SOURCE
#include <assert.h>
#include <errno.h>
#include <fcntl.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
static const char *fixture_root,*receiver_path;
static void *receiver_image;
static unsigned init_calls;
static void provider_init(void) { init_calls++; errno=EADDRNOTAVAIL; }
static unsigned provider_get(int id) { (void)id; abort(); }
static void provider_set(int id,unsigned value) { (void)id;(void)value;abort(); }
static void *lookup(void *handle,const char *symbol) {
    (void)handle;
    if(!strcmp(symbol,"mcmn_param_init"))return provider_init;
    if(!strcmp(symbol,"mcmn_param_getul"))return provider_get;
    if(!strcmp(symbol,"mcmn_param_setul"))return provider_set;
    abort();
}
static void *fake_dlvsym(void *handle,const char *symbol,const char *version) {
    (void)handle;(void)symbol;(void)version;return lookup;
}
static int fake_open(const char *path,int flags,...) {
    if(!strcmp(path,"/dev/console"))return 999;
    if(!strncmp(path,"/simulation/",12)) {
        char local[4096];int n=snprintf(local,sizeof local,"%s%s",fixture_root,path);
        assert(n>0 && n<(int)sizeof local);return open(local,flags);
    }
    return open(path,flags);
}
static long fake_write(int fd,const void *data,unsigned long count) {
    return write(fd==999?1:fd,data,count);
}
static int fake_close(int fd) { return fd==999?0:close(fd); }
static int fake_fflush(void *stream) { (void)stream;return 0; }
struct media_dl_info;
static int fake_dladdr(const void *,struct media_dl_info *);
#define dlvsym fake_dlvsym
#define dladdr fake_dladdr
#define open fake_open
#define write fake_write
#define close fake_close
#define fflush fake_fflush
#include "p1-dev-file-media-config.c"
static int fake_dladdr(const void *function,struct media_dl_info *info) {
    if(receiver_image && function==(char *)receiver_image+0xa758) {
        *info=(struct media_dl_info){.name=receiver_path,.base=receiver_image};return 1;
    }
    return 0;
}
int main(int argc,char **argv) {
    assert(argc==5);fixture_root=argv[1];receiver_path=argv[2];
    if(!strcmp(argv[4],"symbol")) {
        FILE *stream=fopen(receiver_path,"rb");assert(stream);
        receiver_image=malloc(60600);assert(receiver_image && fread(receiver_image,1,60600,stream)==60600);
        assert(!fclose(stream));
        assert(hash_file(receiver_path,60600,"bfaf84e1f2c71056c450640f6752c6cd6c8f84004778506dd6d237ced0bd46f6"));
        assert(!hash_file(argv[3],60600,"bfaf84e1f2c71056c450640f6752c6cd6c8f84004778506dd6d237ced0bd46f6"));
        assert(!hash_file(receiver_path,60599,"bfaf84e1f2c71056c450640f6752c6cd6c8f84004778506dd6d237ced0bd46f6"));
        assert(p1_symbol((char *)receiver_image+0xa758,0xa758,60600,
            "bfaf84e1f2c71056c450640f6752c6cd6c8f84004778506dd6d237ced0bd46f6",236,
            "18b3689b0fc5973c5a82aa5fb510ac03178dda5f1ee469bef3f0e7f506d03249",0));
        ((unsigned char *)receiver_image)[0xa758]^=1;
        assert(!p1_symbol((char *)receiver_image+0xa758,0xa758,60600,
            "bfaf84e1f2c71056c450640f6752c6cd6c8f84004778506dd6d237ced0bd46f6",236,
            "18b3689b0fc5973c5a82aa5fb510ac03178dda5f1ee469bef3f0e7f506d03249",0));
        free(receiver_image);return 0;
    }
    assert(!setenv("A7C2_FILE_MEDIA_TEST","1",1));
    assert(!setenv("A7C2_P1_FILE_MEDIA_PROFILE","original-sd-v1",1));
    assert(!setenv("A7C2_P1_DEV_INSTALL","fixed-system-file-v1",1));
    if(!strcmp(argv[4],"wrong-profile"))assert(!setenv("A7C2_P1_FILE_MEDIA_PROFILE","foreign",1));
    if(!strcmp(argv[4],"wrong-kind"))assert(!setenv("A7C2_P1_DEV_INSTALL","version-only-2.02",1));
    if(!strcmp(argv[4],"off"))unsetenv("A7C2_FILE_MEDIA_TEST");
    mcmn_param_init();
    /* With testing off the real original init and errno still pass through. */
    assert(!strcmp(argv[4],"off") && init_calls==1 && errno==EADDRNOTAVAIL);
    return 0;
}
