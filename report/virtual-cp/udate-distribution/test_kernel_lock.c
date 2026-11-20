/* Test-only implementation of the two original kernel IRQ-lock exports. */
#include <pthread.h>
#include <stdlib.h>
static pthread_mutex_t lock=PTHREAD_MUTEX_INITIALIZER;
unsigned long _raw_spin_lock_irqsave(unsigned int *word)
{
    (void)word;
    if(pthread_mutex_lock(&lock)) abort();
    return 0;
}
void _raw_spin_unlock_irqrestore(unsigned int *word,unsigned long flags)
{
    (void)word;(void)flags;
    if(pthread_mutex_unlock(&lock)) abort();
}
