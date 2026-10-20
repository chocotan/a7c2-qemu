from pathlib import Path
import subprocess


def test_diagnostic_reads_live_pixels_without_replacing_committed_pixels(tmp_path):
    source=r'''
#define _GNU_SOURCE
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "headless-osd.c"
static struct hosd_state state;
static int reads,changed;
static int frame(struct hosd_frame *f,unsigned char *p){(void)f;reads++;memset(p,7,HOSD_PIXELS);return 0;}
static void logline(const char *tag,const char *text){
 if(!strcmp(tag,"OSD_META_PIXELS ")){assert(strstr(text,"different=1"));assert(strstr(text,"observation_only=1"));changed++;}
}
int main(int argc,char **argv){
 assert(argc==2);
 state.pending=0x1005;state.have_descriptor=1;state.pixel_source_seq=1;state.sequence=1;
 state.retained_frame=(struct hosd_frame){0x402,640,480,1,0x438a16100UL};
 memset(state.retained_pixels,1,HOSD_PIXELS);
 put32(state.retained_descriptor+8,0x402);
 state.retained_descriptor[0x14]=0x80;state.retained_descriptor[0x15]=2;
 state.retained_descriptor[0x16]=0xe0;state.retained_descriptor[0x17]=1;
 struct hosd_ops ops={0};ops.frame=frame;ops.log=logline;
 assert(!setenv("MENU_OSD_META_PIXELS","1",1));assert(!consume(&state,&ops,argv[1]));
 assert(reads==1 && changed==1 && state.sequence==2 && state.pixel_source_seq==1);
 FILE *fp=fopen(argv[1],"rb");assert(fp);assert(!fseek(fp,HOSD_HEADER+sizeof state.frozen,SEEK_SET));
 for(unsigned int i=0;i<HOSD_PIXELS;i++)assert(fgetc(fp)==1);
 assert(!fclose(fp));assert(!unsetenv("MENU_OSD_META_PIXELS"));
 assert(!consume(&state,&ops,argv[1]));assert(reads==1 && changed==1);
 return 0;
}
'''
    test=tmp_path/'meta.c';binary=tmp_path/'meta';test.write_text(source)
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined',
                    '-I',str(Path(__file__).parent),str(test),'-o',str(binary)],check=True)
    subprocess.run([str(binary),str(tmp_path/'frame.bin')],check=True,capture_output=True)
