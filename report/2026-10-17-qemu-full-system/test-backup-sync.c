#include <assert.h>
#include <string.h>
#define BACKUP_SYNC_TEST
#include "backup-sync.c"

static unsigned calls,last_subsystem;static int original_result;
int Backup_sync_all(void) {calls++;last_subsystem=0x10000;return original_result;}
int Backup_sync_subsystem(unsigned subsystem) {calls++;last_subsystem=subsystem;return original_result;}

int main(void) {
    unsigned number;
    assert(subsystem_number("0",&number) && !number);
    assert(subsystem_number("0x2cf",&number) && number==0x2cf);
    assert(subsystem_number("65535",&number) && number==65535);
    const char *invalid[]={"","0x","65536","0x10000","-1","+1"," 1","1 ","0xgg","1a","99999999999999999999999"};
    for (unsigned i=0;i<sizeof invalid/sizeof invalid[0];i++)assert(!subsystem_number(invalid[i],&number));
    assert(!subsystem_number(0,&number));
    char *sub[]={"backup-sync","--subsystem","0x2cf"};
    assert(!run(3,sub) && calls==1 && last_subsystem==0x2cf);
    char *all[]={"backup-sync","--all"};original_result=-7;
    assert(run(2,all)==1 && calls==2 && last_subsystem==0x10000);
    original_result=4;assert(run(2,all)==1 && calls==3);
    char *bad[]={"backup-sync","--subsystem","65536"};
    assert(run(3,bad)==2 && run(1,all)==2 && run(0,0)==2 && calls==3);
    return 0;
}
