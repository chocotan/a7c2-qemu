/* Included only in an explicitly selected stock tail observer build. */
#ifndef P1_TAIL_BUDGET_H
#define P1_TAIL_BUDGET_H
#include <stddef.h>
#include <stdint.h>
enum { T_ID, T_SIG, T_FORMAT, T_BACKEND, T_WRITER, T_PLUGIN, T_END, T_FAILURE, T_FAMILIES };
static const unsigned tail_limit[T_FAMILIES]={12,16,32,40,64,40,24,28};
struct tail_budget { uint64_t seen[T_FAMILIES], dropped[T_FAMILIES]; unsigned used[T_FAMILIES], records, bytes; };
/* Call under the epoch lock. Rejected records count; no family can borrow another reservation. */
static int tail_reserve(struct tail_budget *b,unsigned f,size_t n) {
    if(f>=T_FAMILIES)return 0;
    b->seen[f]++;
    if(!n || n>1024 || b->used[f]>=tail_limit[f] || b->records>=256 || n>262144-b->bytes) {
        b->dropped[f]++;return 0;
    }
    b->used[f]++;b->records++;b->bytes+=(unsigned)n;return 1;
}
static int tail_raw_target(const char *p) {
    static const char *const paths[]={"/dev/nflasha3","/dev/nflasha5","/dev/nflasha7","/dev/nflasha8","/dev/nflasha15",
        "/dev/cnflasha3","/dev/cnflasha5","/dev/cnflasha7","/dev/cnflasha8","/dev/cnflasha15"};
    for(unsigned i=0;i<10;i++)if(!strcmp(p,paths[i]))return (int)(i%5);
    return -1;
}
#endif
