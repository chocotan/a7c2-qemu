#define RAMFB_TEST
#include "ramfb-viewer.c"
#include <assert.h>
static unsigned char frame[HOSD_BYTES], output[XRGB_BYTES];
int main(int argc,char **argv) {
    assert(argc==2);
    const char *names[]={"ui-0","ui-47","ui-65","ui-70","ui-73"};
    for(unsigned n=0;n<5;n++) {
        char path[8192];assert(snprintf(path,sizeof path,"%s/%s.bin",argv[1],names[n])<(int)sizeof path);
        int fd=open(path,O_RDONLY);assert(fd>=0);assert(!read_all(fd,frame,sizeof frame));close(fd);
        assert(!validate(frame,sizeof frame));
        preview_enabled=1;assert(!convert_frame(frame,output));assert(preview_active==(n==4));
        assert(!validate(frame,sizeof frame));
        printf("REAL_SCENE_PASS name=%s virtual_preview=%d source_unchanged=1\n",names[n],preview_active);
    }
    free(preview_rgb);return 0;
}
