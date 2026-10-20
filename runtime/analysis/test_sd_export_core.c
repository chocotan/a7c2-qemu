#define SD_EXPORT_TEST
#include "sd-window-export.c"
#include <assert.h>
#include <stdio.h>

static unsigned char mapped[SD_CAP];
struct fake { int identities, maps, mode, interrupted; };
static int test_identity(void *context, struct sd_identity *out) {
    struct fake *f=context;
    *out=(struct sd_identity){1,7,32,100,101,2,3};
    if (f->mode==1 && f->identities) out->inode++;
    if (f->mode==2 && f->identities) out->mtime_ns++;
    if (f->mode==3 && f->identities) out->ctime++;
    if (f->mode==4 && f->identities) out->total--;
    f->identities++;
    return f->mode==5 ? -1 : 0;
}
static unsigned char *test_window(void *context) {
    struct fake *f=context;
    f->maps++;
    return f->mode==6 ? 0 : mapped;
}
static long test_read(void *context, unsigned char *buffer, size_t count, uint64_t offset) {
    struct fake *f=context;
    if (!f->interrupted++) { errno=EINTR; return -1; }
    if (f->mode==7) return 0;
    if (f->mode==8) { errno=EIO; return -1; }
    if (f->mode==9) return count+1;
    if (count>3) count=3;
    for (size_t i=0;i<count;i++) buffer[i]=(unsigned char)(offset+i);
    return count;
}
int main(void) {
    assert(sd_reserved(SD_RESERVATION));
    assert(sd_reserved(SD_COMBINED_RESERVATION));
    assert(!sd_reserved(SD_RESERVATION " " SD_COMBINED_RESERVATION));
    uint64_t number=0;
    assert(!sd_number("9223372036854775807",&number) && number==INT64_MAX);
    const char *invalid[]={"","-1","+1","1a","0x10"," 1","1 ","9223372036854775808","99999999999999999999999999"};
    for (unsigned i=0;i<sizeof invalid/sizeof *invalid;i++) assert(sd_number(invalid[i],&number));
    assert(!sd_number("0",&number) && !number);
    assert(sd_reserved(SD_RESERVATION));
    assert(sd_reserved("quiet\t" SD_RESERVATION "\n"));
    assert(!sd_reserved("x" SD_RESERVATION));
    assert(!sd_reserved(SD_RESERVATION "x"));
    assert(!sd_reserved(SD_RESERVATION " " SD_RESERVATION));
    assert(!sd_reserved(""));
    struct fake f={0};
    struct sd_io io={&f,SD_RESERVATION,test_identity,test_window,test_read};
    struct sd_result out;
    memset(mapped,255,sizeof mapped);
    assert(!sd_export(&io,4,16,32,&out));
    uint64_t hash=UINT64_C(14695981039346656037);
    for (unsigned i=0;i<16;i++) { assert(mapped[i]==i+4); hash=(hash^mapped[i])*UINT64_C(1099511628211); }
    for (unsigned i=16;i<SD_CAP;i++) assert(!mapped[i]);
    assert(out.fnv==hash && f.maps==1 && f.identities==2);
    const uint64_t bounds[][3]={{0,0,32},{0,SD_CAP+1,SD_CAP+1},{31,2,32},
        {33,1,32},{UINT64_MAX,1,32},{0,1,0},{0,1,UINT64_MAX}};
    for (unsigned i=0;i<sizeof bounds/sizeof *bounds;i++) {
        f=(struct fake){0};
        assert(sd_export(&io,bounds[i][0],bounds[i][1],bounds[i][2],&out)==2 && !f.maps);
    }
    io.cmdline="quiet";
    assert(sd_export(&io,0,16,32,&out)==3);
    io.cmdline=SD_RESERVATION;
    f=(struct fake){0};
    assert(sd_export(&io,0,16,31,&out)==4 && !f.maps);
    for (int mode=1;mode<=9;mode++) {
        f=(struct fake){.mode=mode};
        assert(sd_export(&io,0,16,32,&out)!=0);
    }
    puts("SD_EXPORT_TEST core: ranges/reservation/partial/EINTR/truncate/identity/zero-tail PASS");
    return 0;
}
