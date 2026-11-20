/*
 * Standalone DWARF type carrier for the kernel structures the model17c GDB
 * owner reads. It is never loaded, linked into the guest or executed: the
 * build keeps only its DWARF (see build-kernel-types.py).
 *
 * The persistent-flash module cannot serve as the type source. Its build uses
 * the kernel's reduced-debug flags, and -femit-struct-debug-baseonly drops
 * every structure defined outside this compilation unit.
 */
#include <linux/sched.h>
#include <linux/fs.h>
#include <linux/mm.h>
#include <linux/path.h>
#include <linux/seqlock.h>
#include <linux/spinlock.h>

/*
 * include/linux/fs_struct.h is not part of the 406-header dependency subset.
 * The definition is copied verbatim from the product Sony Linux 4.9.337 source
 * (include/linux/fs_struct.h) that built the running guest kernel.
 */
struct fs_struct {
	int users;
	spinlock_t lock;
	seqcount_t seq;
	int umask;
	int in_exec;
	struct path root, pwd;
};

/*
 * Reads exactly the fields model17c_startup.py dereferences, so the emitted
 * DWARF carries the real member offsets of the current ABI headers instead of
 * pointer-only declarations.
 */
unsigned long kernel_types_probe(struct task_struct *task)
{
	struct mm_struct *mm = task->mm;
	struct vm_area_struct *vma = mm->mmap;
	struct fs_struct *fs = task->fs;
	unsigned long sum = task->pid + task->tgid;

	sum += (unsigned long)mm->pgd + mm->env_start + mm->env_end;
	sum += (unsigned long)fs->root.mnt + (unsigned long)fs->root.dentry;
	while (vma) {
		sum += vma->vm_start + vma->vm_end + vma->vm_flags + vma->vm_pgoff;
		sum += (unsigned long)vma->vm_mm - (unsigned long)mm;
		if (vma->vm_file) {
			struct file *file = vma->vm_file;
			struct dentry *dentry = file->f_path.dentry;

			sum += (unsigned long)file->f_path.mnt;
			sum += (unsigned long)dentry->d_parent;
			sum += (unsigned long)dentry->d_name.name;
			sum += file->f_inode->i_ino + file->f_inode->i_sb->s_dev;
		}
		vma = vma->vm_next;
	}
	return sum;
}
