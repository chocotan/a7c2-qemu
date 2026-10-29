"""Firstboot factory logs are not a substitute for a visible LCD choice."""
import importlib.util
from pathlib import Path

from PIL import Image,ImageDraw
import pytest

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('reader_boot_gtk',HERE/'check-natural-gtk-input.py')
probe=importlib.util.module_from_spec(spec);spec.loader.exec_module(probe)


def paint(path,choice):
    image=Image.new('RGB',(640,480),'black')
    if choice in ('upper','lower'):
        ImageDraw.Draw(image).rectangle((30,14,609,411),outline=(68,68,68))
    if choice=='upper':image.paste((180,64,0),(200,275,440,330))
    elif choice in ('lower','underlying-lower'):image.paste((180,64,0),(200,340,440,395))
    else:image.paste((180,64,0),(24,77,622,128))  # old accessibility page
    image.save(path)


def test_stale_lcd_and_late_selection_never_cause_early_or_duplicate_down(tmp_path):
    path=tmp_path/'lcd.png';choices=['none','upper','upper','lower'];state={'index':0};events=[]
    paint(path,choices[0])
    def refresh(attempt):
        events.append(('refresh',attempt));state['index']+=1;paint(path,choices[state['index']])
    def down():
        assert choices[state['index']]=='upper';events.append(('down',state['index']))
    result=probe.select_reader_later(lambda:path,refresh,down)
    assert events==[('refresh',0),('down',1),('refresh',1),('refresh',2)]
    assert result['highlight_verified'] and result['dialog_frame_verified'] and result['down_sent'] and result['refreshes']==3
    assert result['lower_orange_pixels']>1000 and not result['upper_orange_pixels']


def test_already_later_selected_sends_no_extra_navigation(tmp_path):
    path=tmp_path/'lcd.png';paint(path,'lower')
    def unexpected(*args):raise AssertionError('already selected must not navigate or refresh')
    result=probe.select_reader_later(lambda:path,unexpected,unexpected)
    assert result['highlight_verified'] and not result['down_sent'] and result['refreshes']==0


def test_last_allowed_refresh_is_still_checked(tmp_path):
    path=tmp_path/'lcd.png';paint(path,'upper');events=[]
    def refresh(attempt):
        events.append('refresh')
        if attempt==11:paint(path,'lower')
    result=probe.select_reader_later(lambda:path,refresh,lambda:events.append('down'))
    assert result['highlight_verified'] and result['refreshes']==12
    assert events.count('down')==1 and events.count('refresh')==12


@pytest.mark.parametrize('choice,expected_down',[('none',0),('upper',1),('underlying-lower',0)])
def test_ambiguous_or_unconsumed_selection_stops_without_confirm(tmp_path,choice,expected_down):
    path=tmp_path/'lcd.png';paint(path,choice);events=[]
    with pytest.raises(RuntimeError,match='no confirm input sent'):
        probe.select_reader_later(lambda:path,lambda n:events.append('refresh'),lambda:events.append('down'))
    assert events.count('down')==expected_down and events.count('refresh')==12
