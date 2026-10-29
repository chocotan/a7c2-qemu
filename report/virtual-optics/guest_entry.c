/* SPDX-License-Identifier: MIT */
/* Same libc-2.25 startup pattern as the existing native guest helpers. */
extern int main(void);
extern int __libc_start_main(int (*)(int, char **), int, char **,
                             void (*)(void), void (*)(void), void (*)(void), void *);

static int run(int argc, char **argv)
{
    (void)argc;
    (void)argv;
    return main();
}

__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl optics_entry\nbrk #0\n");
__attribute__((noreturn)) void optics_entry(unsigned long *stack)
{
    __libc_start_main(run, (int)stack[0], (char **)(stack + 1), 0, 0, 0, stack);
    __builtin_trap();
}
