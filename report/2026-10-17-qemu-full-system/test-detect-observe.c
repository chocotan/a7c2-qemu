/* A read-only observer must preserve each parser's return value and arguments. */
#define dlsym mock_dlsym
#include "detect-observe.c"
#include <assert.h>

static unsigned char object[0x400];
static unsigned char message[16];
static int original_rm(void *self, unsigned int id, void *msg) {
    assert(self==object && id==0x80000005u && msg==message);
    assert(parsing==1);
    return -73;
}
static int original_base(void *self, void *msg) {
    assert(self==object && msg==message);
    return 5;
}
void *mock_dlsym(void *handle,const char *name) {
    assert(handle==RTLD_NEXT);
    if (!strcmp(name,"_ZN24InfraMediaDetectThreadRM20ParseInternalMessageEjPN3MWF6ObjMsgE"))return original_rm;
    if (!strcmp(name,"_ZN26InfraMediaDetectThreadBase12ParseMessageEPN3MWF6ObjMsgE"))return original_base;
    assert(0);
    return 0;
}
int main(void) {
    enabled=0;
    assert(_ZN24InfraMediaDetectThreadRM20ParseInternalMessageEjPN3MWF6ObjMsgE(
        object,0x80000005u,message)==-73);
    assert(parsing==0);
    assert(_ZN26InfraMediaDetectThreadBase12ParseMessageEPN3MWF6ObjMsgE(object,message)==5);
    return 0;
}
