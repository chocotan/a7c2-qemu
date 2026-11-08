/*
 * include/linux/trace_kmalloc.h
 *
 *
 * Copyright 2012 Sony Corporation
 * Copyright 2019 Sony Imaging Products & Solutions Inc
 *
 *  This program is free software; you can redistribute  it and/or modify it
 *  under  the terms of  the GNU General  Public License as published by the
 *  Free Software Foundation;  version 2 of the  License.
 *
 *  THIS  SOFTWARE  IS PROVIDED   ``AS  IS'' AND   ANY  EXPRESS OR IMPLIED
 *  WARRANTIES,   INCLUDING, BUT NOT  LIMITED  TO, THE IMPLIED WARRANTIES OF
 *  MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE DISCLAIMED.  IN
 *  NO  EVENT  SHALL   THE AUTHOR  BE    LIABLE FOR ANY   DIRECT, INDIRECT,
 *  INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT
 *  NOT LIMITED   TO, PROCUREMENT OF  SUBSTITUTE GOODS  OR SERVICES; LOSS OF
 *  USE, DATA,  OR PROFITS; OR  BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
 *  ANY THEORY OF LIABILITY, WHETHER IN  CONTRACT, STRICT LIABILITY, OR TORT
 *  (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF
 *  THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
 *
 *  You should have received a copy of the  GNU General Public License along
 *  with this program; if not, write  to the Free Software Foundation, Inc.,
 *  51 Franklin Street, Suite 500, Boston, MA 02110-1335, USA.
 *
 */

#ifndef __TRACE_KMALLOC_H__
#define __TRACE_KMALLOC_H__

#ifdef CONFIG_KMALLOC_SIMPLE_TRACE
extern int kmalloc_add_trace(unsigned long addr, size_t size, gfp_t flags);
extern int kmalloc_add_trace_entry(unsigned long addr, size_t size, gfp_t flags, unsigned long caller);
extern int kmalloc_del_trace_entry(unsigned long addr);
#else
# define kmalloc_add_trace(addr, size, flags)		    do {} while (0)
# define kmalloc_add_trace_entry(addr, size, flags, caller) do {} while (0)
# define kmalloc_del_trace_entry(addr)			    do {} while (0)
#endif

#endif /* __TRACE_KMALLOC_H__ */
