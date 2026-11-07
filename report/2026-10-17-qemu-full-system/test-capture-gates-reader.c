/* Host ABI mocks; no process memory is opened or changed. */
#include <assert.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#undef strstr
static int map_lines,reads,short_read,closed;
static char output[20000];static unsigned written;
static void *fake_fopen(const char *path,const char *mode) {
    assert(!strcmp(path,"/proc/444/maps") && !strcmp(mode,"r"));map_lines=0;return (void *)1;
}
static char *fake_fgets(char *line,int length,void *stream) {
    assert(stream==(void *)1 && length>=100);
    if(map_lines++)return 0;
    strcpy(line,"7f00000000-7f08000000 r-xp 00000000 00:00 1 /usr/lib/appFw.so\n");return line;
}
static int fake_fclose(void *stream) {assert(stream==(void *)1);return 0;}
static int fake_open(const char *path,int flags,...) {
    assert(!strcmp(path,"/proc/444/mem") && flags==0x80000);return 7;
}
static long fake_pread(int fd,void *bytes,unsigned long size,long address) {
    assert(fd==7 && (size==1 || size==4) && address>0x7f00000000L);reads++;
    memset(bytes,0,size);return reads==short_read?0:(long)size;
}
static int fake_close(int fd) {assert(fd==7);closed++;return 0;}
static int fake_fflush(void *stream) {(void)stream;return 0;}
static int fake_printf(const char *format,...) {
    va_list args;va_start(args,format);
    int n=vsnprintf(output+written,sizeof output-written,format,args);va_end(args);
    assert(n>=0 && (unsigned)n<sizeof output-written);written+=(unsigned)n;return n;
}
#define CAPTURE_READER_TEST 1
#define fopen fake_fopen
#define fgets fake_fgets
#define fclose fake_fclose
#define open fake_open
#define pread fake_pread
#define close fake_close
#define fflush fake_fflush
#define printf fake_printf
#include "capture-gates-reader.c"
int main(void) {
    char *args[]={"capture-gates-reader","444","2"};
    assert(!run(3,args) && reads==37 && closed==1);
    assert(strstr(output,"CAPTURE_GATE_BEGIN_system_mode_end"));
    reads=written=closed=0;short_read=5;
    assert(run(3,args)==5 && reads==5 && closed==1);
    assert(strstr(output,"CAPTURE_GATE_READ_FAILED"));
    unsigned long value;
    assert(!decimal("99999999999999999999999999999999999999",2147483647UL,&value));
    assert(!decimal("3",2,&value));assert(!decimal("",2,&value));
    assert(decimal("2",2,&value) && value==2);
    args[1]="0";assert(run(3,args)==2);
    return 0;
}
