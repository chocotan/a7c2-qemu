import hashlib
from PIL import Image,ImageDraw
import pytest
import format_prompt_review as review


def fixture(tmp_path,monkeypatch):
    image=Image.new('RGB',(640,480));draw=ImageDraw.Draw(image)
    draw.rectangle((201,341,437,393),fill=(170,51,0))
    reference=tmp_path/'reference.png';image.save(reference)
    monkeypatch.setattr(review,'REVIEWED_RGB_SHA256',hashlib.sha256(image.tobytes()).hexdigest())
    draw.rectangle((201,341,437,393),fill=(0,0,0))
    draw.rectangle((201,276,437,327),fill=(170,51,0))
    selected=tmp_path/'selected.png';image.save(selected)
    return reference,selected


def test_only_confirmed_selected_original_popup_allows_enter(tmp_path,monkeypatch):
    reference,selected=fixture(tmp_path,monkeypatch)
    proof=review.require_confirm_selected(reference,selected)
    assert proof['original_confirm_selection_verified'] and not proof['original_format_verified']
    with pytest.raises(ValueError,match='selection not visible'):review.require_confirm_selected(reference,reference)


def test_black_other_page_and_changed_size_refuse_confirmation(tmp_path,monkeypatch):
    reference,selected=fixture(tmp_path,monkeypatch)
    for name,size,pixel in (('black',(640,480),None),('other',(640,480),(2,2)),('small',(320,240),None)):
        path=tmp_path/(name+'.png')
        image=Image.new('RGB',size)
        if pixel:
            image=Image.open(selected).copy();image.putpixel(pixel,(255,255,255))
        image.save(path)
        with pytest.raises(ValueError):review.require_confirm_selected(reference,path)
    with pytest.raises(ValueError):review.require_reviewed_cancel(selected)
