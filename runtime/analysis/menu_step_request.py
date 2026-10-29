"""Bounded, reviewed-page manual key requests; no raw commands or API calls."""
KEYS=frozenset(('UP','DOWN','LEFT','RIGHT','ENTER','MENU'))


def validate(request, expected):
    if not isinstance(request,dict) or set(request)!={'step','key'}:
        raise ValueError('Menu request must contain only step and key')
    if type(request['step']) is not int or request['step']!=expected or not 1<=expected<=80:
        raise ValueError('Menu request step out of order/bounds')
    if request['key'] not in KEYS|{'FINISH'}:
        raise ValueError('Only ordinary menu navigation or FINISH is allowed')
    return request['key']


def await_checkpoint(folder,check,seconds):
    """Linux file events, not screenshot polling; a bounded interactive-test checkpoint."""
    import ctypes,os,select,time
    library=ctypes.CDLL(None,use_errno=True)
    fd=library.inotify_init1(os.O_CLOEXEC|os.O_NONBLOCK)
    if fd<0:raise OSError(ctypes.get_errno(),'inotify_init1')
    try:
        if library.inotify_add_watch(fd,os.fsencode(folder),0x000001ca)<0:
            raise OSError(ctypes.get_errno(),'inotify_add_watch')
        deadline=time.monotonic()+seconds
        while True:
            result=check()
            if result:return result
            remaining=deadline-time.monotonic()
            if remaining<=0 or not select.select([fd],[],[],remaining)[0]:
                raise TimeoutError('Reviewed menu checkpoint did not complete')
            os.read(fd,65536)
    finally:os.close(fd)


def main():
    import argparse,json,os,re,uuid
    from pathlib import Path
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=('ready','step'))
    parser.add_argument('path',type=Path)
    parser.add_argument('--step',type=int)
    parser.add_argument('--key')
    args=parser.parse_args()
    if args.mode=='ready':
        def ready():
            try:text=args.path.read_text(errors='replace')
            except FileNotFoundError:return None
            if len(text)>4*1024*1024:raise ValueError('Workflow log exceeds bound')
            match=re.search(r'^FORMAT_WORKFLOW_READY (\S+)\s*$',text,re.M)
            if match:
                run=Path(match[1])
                manifest=json.loads((run/'runtime-manifest.json').read_text())
                if manifest.get('host_sd_profile')!='host-file-usb-256gb-v1':
                    raise ValueError('Not the requested host256GB card profile')
                for name in ('gtk-simplified-chinese-selected.png','gtk-shooting-after-setup.png','gtk-menu-stable.png'):
                    if not (run/name).is_file():raise ValueError('Missing actual Chinese/HUD/menu image')
                return {'ready':True,'run':str(run),'formatted_by_camera':False}
            if 'Traceback (most recent call last)' in text:raise RuntimeError('UI workflow failed before readiness')
        result=await_checkpoint(args.path.parent,ready,360)
    else:
        request={'step':args.step,'key':args.key};validate(request,args.step)
        run=args.path
        if not (run/'gtk-menu-stable.png').is_file():raise ValueError('Reviewed menu workflow not ready')
        pending=run/('.format-request-'+uuid.uuid4().hex)
        try:
            with pending.open('x') as file:
                json.dump(request,file);file.flush();os.fsync(file.fileno())
            os.link(pending,run/'format-step.request.json')
        finally:pending.unlink(missing_ok=True)
        if args.key=='FINISH':result={'submitted':True,'completed':False,'step':args.step}
        else:
            image=run/f'gtk-format-step-{args.step:02d}-{args.key.lower()}.png'
            def captured():
                if not image.is_file():return None
                from PIL import Image
                try:
                    with Image.open(image) as png:png.verify()
                except (OSError,SyntaxError):return None
                return {'step':args.step,'key':args.key,'image':str(image),'visual_review_required':True}
            result=await_checkpoint(run,captured,60)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
