/* Verify ownership transfer against an immediately consuming receiver. */
#define CP_RM_NOTIFY_TEST
#include <assert.h>
#include <string.h>
#include "cp-rm-notify.c"

static unsigned char storage[7];
static int sent, reject_send, freed;
int osal_valloc_msg_wait(unsigned int sid, void **out, unsigned int bytes, int count) {
    assert(sid == MEDIA_STATE_SID && bytes == 7 && count == 1);
    *out = storage;
    return 0;
}
unsigned int osal_msg_size(void *p) {
    assert(p == storage && !sent); /* No access is permitted after send. */
    return 7;
}
int osal_snd_msg(unsigned int sid, void *p) {
    assert(sid == MEDIA_STATE_SID && p == storage && !sent);
    assert(!memcmp(p, (unsigned char[]){2,0,0,7,0,2,0}, 7));
    if (reject_send) return -88;
    sent = 1;
    memset(storage, 0xa5, 7); /* Receiver consumed/freed the payload synchronously. */
    return 0;
}
int osal_free_msg(unsigned int sid, void *p) {
    assert(sid == MEDIA_STATE_SID && p == storage && !sent);
    ++freed;
    return 0;
}
int main(void) {
    char *args[] = {"cp-rm-notify", "2", "0", "0", "7", "0", "2", "0"};
    assert(run(8, args) == 0 && sent && !freed);
    sent = 0; reject_send = 1;
    assert(run(8, args) == 4 && !sent && freed == 1);
    args[2] = "1";
    assert(run(8, args) == 2); /* Producer's reserved header byte must stay zero. */
    unsigned int value;
    assert(!parse_byte("", &value));
    return 0;
}
