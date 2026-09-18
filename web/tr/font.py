from os import path
from fontTools import subset
from fontTools.ttLib import TTFont, woff2
from fontTools.merge import Merger


def get_supported_chars(chars, font_path):
    """得到字体支持的字符集合"""
    font = TTFont(font_path, fontNumber=0)
    for table in font['cmap'].tables:
        for c_code in table.cmap:
            chars.add(c_code)
    return chars


def check_font_export_svg():
    """检查缺漏字并导出相应的字SVG"""
    chars_a, chars_b = set(), set()
    with open(path.join(_path, 'JS.tmp.txt'), encoding='utf-8') as f:
        for s in f.readlines():
            chars_a.add(ord(s[0]))
    for fn in ['SimSun-3.03.ttc', 'SimSun-5.16.ttc', 'MsYaHei-5.0.ttf', 'MsYaHei-6.25.ttf']:
        get_supported_chars(chars_b, path.join(_path, 'font.tmp', fn))
    chars_c = sorted(list(chars_a - chars_b))

    ref_file, picks = ['KaiXinSongB.ttf', 'KaiXinSongA.ttf'], {}
    ref_chars = [get_supported_chars(set(), path.join(_path, 'font.tmp', f)) for f in ref_file]
    for c in chars_c:
        for i, chars in enumerate(ref_chars):
            if c in chars:
                picks[c] = i + 1
                break
        else:  # ⊖⊗⌽◉◐◑◒◓◬☰☱☲☳☴☵☶☷⚌⚍⟁⦵⦶⦻⧇ 2296~29c7
            pass

    opt = subset.Options()
    for i in range(2):
        chars = [chr(c) for c in chars_c if picks.get(c) == i + 1]
        font = subset.load_font(path.join(_path, 'font.tmp', ref_file[i]), opt)
        setter = subset.Subsetter()
        setter.populate(text=''.join(chars))
        setter.subset(font)
        subset.save_font(font, path.join(_path, 'out.tmp', ref_file[i]), opt)

    font = Merger().merge([path.join(_path, 'out.tmp', ref_file[i]) for i in range(2)])
    font.save(path.join(_path, 'out.tmp', 'KaixinsongMini.ttf'))
    woff2.compress(path.join(_path, 'out.tmp', 'KaixinsongMini.ttf'),
                   path.join(_path, 'out.tmp', 'KaixinsongMini.woff2'))


_path = path.dirname(__file__)
check_font_export_svg()
