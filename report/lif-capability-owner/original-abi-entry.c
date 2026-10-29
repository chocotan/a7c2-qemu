/* Execute the existing HOST_TEST C scenarios with firmware libc. */
#include <stdint.h>
#include <stdlib.h>
extern int main(int, char **);
__attribute__((noreturn)) void original_abi_entry(uintptr_t *stack)
{
    exit(main((int)stack[0], (char **)(stack + 1)));
}
__attribute__((naked)) void _start(void)
{
    __asm__("mov x0, sp\n"
            "bl original_abi_entry\n"
            "mov x8, #93\n"
            "svc #0\n");
}
