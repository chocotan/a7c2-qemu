/* Original-glibc startup only; all libc/pthread operations link the originals. */
#ifdef UNIT_MAIN_ARGV
extern int main(int,char **);
static int run(int argc,char **argv){return main(argc,argv);}
#else
extern int main(void);
static int run(int argc,char **argv){(void)argc;(void)argv;return main();}
#endif
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start, %function\n_start:\nmov x0, sp\nbl entry\nbrk #0\n");
__attribute__((noreturn)) void entry(unsigned long *stack){
    __libc_start_main(run,(int)stack[0],(char **)(stack+1),0,0,0,stack);__builtin_trap();
}
