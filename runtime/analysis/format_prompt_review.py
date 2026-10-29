"""Only the actually reviewed original Chinese blank-card popup, never a blind key list."""
import hashlib
from PIL import Image

REVIEWED_RGB_SHA256='1c37c08dadda318c302be74aa246c494c79334b627d862a62cf49197bbc9dc90'
UPPER=(199,273,441,331)
LOWER=(199,339,441,397)


def read(path):
    with Image.open(path) as image:
        if image.size!=(640,480) or image.mode!='RGB':raise ValueError('Original LCD geometry/mode changed')
        return image.copy()


def require_reviewed_cancel(path):
    image=read(path)
    if hashlib.sha256(image.tobytes()).hexdigest()!=REVIEWED_RGB_SHA256:
        raise ValueError('Not the visually reviewed original 无法使用存储卡。格式化？ popup')
    return image


def require_confirm_selected(reference,path):
    original=require_reviewed_cancel(reference);actual=read(path)
    old,new=bytearray(original.tobytes()),bytearray(actual.tobytes())
    for left,top,right,bottom in (UPPER,LOWER):
        for y in range(top,bottom):
            start=(y*640+left)*3;end=(y*640+right)*3
            old[start:end]=bytes(end-start);new[start:end]=bytes(end-start)
    if old!=new:raise ValueError('Page changed outside reviewed popup button bounds')
    upper=actual.crop((201,276,438,328));lower=actual.crop((201,341,438,394))
    if upper.tobytes().count(bytes((170,51,0)))<10000 or lower.tobytes().count(bytes((0,0,0)))<10000:
        raise ValueError('Original 确定 selection not visible; do not press ENTER')
    return {'original_cancel_popup_verified':True,'original_confirm_selection_verified':True,
            'original_format_verified':False,'internal_format_api_called':False}
