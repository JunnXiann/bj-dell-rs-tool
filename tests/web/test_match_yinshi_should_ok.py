from web.tw import match_yinshi as my


def plain(sutra, sx_sutra, nums):
    return [('FZ%04d_%03d' % (sutra, n), 'SX%04d_%03d' % (sx_sutra, n)) for n in nums]


def test_windows_follow_previous_z_row():
    # FZ0002: 010z1 覆盖001-010，011z1只覆盖011，012z1只覆盖012
    rows = plain(2, 2, range(1, 11)) + [('FZ0002_010z1', None)]
    rows += plain(2, 2, [11]) + [('FZ0002_011z1', None)]
    rows += plain(2, 2, [12]) + [('FZ0002_012z1', None)]
    existing = {'FZ0002_010z1': '音释', 'FZ0002_011z1': '音释', 'FZ0002_012z1': '音释'}
    windows, skipped = my.build_yinshi_windows(rows, existing)
    assert skipped == []
    assert windows['FZ0002_010z1']['fz_reels'] == ['FZ0002_%03d' % n for n in range(1, 11)]
    assert windows['FZ0002_010z1']['sx_reels'] == ['SX0002_%03d' % n for n in range(1, 11)]
    assert windows['FZ0002_011z1']['fz_reels'] == ['FZ0002_011']
    assert windows['FZ0002_012z1']['sx_reels'] == ['SX0002_012']


def test_sheet_z_row_missing_in_db_is_not_a_boundary():
    rows = plain(1, 1, range(101, 111)) + [('FZ0001_110z1', None)]
    rows += plain(1, 1, range(111, 121)) + [('FZ0001_120z1', None)]
    rows += plain(1, 1, range(121, 131)) + [('FZ0001_130z1', None)]
    # 120z1 不在库里：忽略，130z1 覆盖 111-130
    windows, skipped = my.build_yinshi_windows(rows, {'FZ0001_110z1': '音释', 'FZ0001_130z1': '音释'})
    assert skipped == ['FZ0001_120z1']
    assert windows['FZ0001_130z1']['fz_reels'][0] == 'FZ0001_111'
    assert windows['FZ0001_130z1']['fz_reels'][-1] == 'FZ0001_130'
    assert len(windows['FZ0001_130z1']['fz_reels']) == 20
    # 120z1 在库里但是音释（缺）：是真实分界，130z1 只覆盖 121-130，且120z1不产生任务
    existing = {'FZ0001_110z1': '音释', 'FZ0001_120z1': '音释（缺）', 'FZ0001_130z1': '音释'}
    windows, skipped = my.build_yinshi_windows(rows, existing)
    assert skipped == []
    assert windows['FZ0001_130z1']['fz_reels'][0] == 'FZ0001_121'
    assert windows['FZ0001_120z1']['fz_reels'][0] == 'FZ0001_111'
    ids = [j['id'] for j in my.build_jobs(windows, 'fz2sx')]
    assert 'FZ0001_120z1' not in ids and 'FZ0001_130z1' in ids


def test_sx_reels_come_from_column_b_not_string_replace():
    rows = plain(9, 8, range(1, 8)) + [('FZ0009_007z1', None)]  # 福州藏第9经对应思溪藏第8经
    windows, _ = my.build_yinshi_windows(rows, {'FZ0009_007z1': '音释'})
    assert windows['FZ0009_007z1']['sx_reels'] == ['SX0008_%03d' % n for n in range(1, 8)]


def test_blank_sx_and_x_reels_and_sx_own_z_reel():
    rows = [('FZ0033_001x1', 'SX0027_001x1'), ('FZ0033_001x2', None), ('FZ0033_001', 'SX0027_001'),
            ('FZ0033_002', None), ('FZ0033_002z1', 'SX0027_002z1')]
    windows, _ = my.build_yinshi_windows(rows, {'FZ0033_002z1': '音释'})
    w = windows['FZ0033_002z1']
    assert w['fz_reels'] == ['FZ0033_001x1', 'FZ0033_001x2', 'FZ0033_001', 'FZ0033_002']
    assert w['sx_reels'] == ['SX0027_001x1', 'SX0027_001', 'SX0027_002z1']  # 空白跳过，思溪藏自己的音释卷追加


def test_z1_and_z2_share_window():
    rows = plain(3, 3, range(1, 11)) + [('FZ0003_010z1', None), ('FZ0003_010z2', None)]
    windows, _ = my.build_yinshi_windows(rows, {'FZ0003_010z1': '音释', 'FZ0003_010z2': '音释'})
    assert windows['FZ0003_010z2']['fz_reels'] == windows['FZ0003_010z1']['fz_reels']
    assert windows['FZ0003_010z2']['sx_reels'] == windows['FZ0003_010z1']['sx_reels']


def test_jobs_for_both_directions():
    rows = plain(3, 3, range(1, 11)) + [('FZ0003_010z1', None), ('FZ0003_010z2', None)]
    windows, _ = my.build_yinshi_windows(rows, {'FZ0003_010z1': '音释', 'FZ0003_010z2': '音释'})
    sx = ['SX0003_%03d' % n for n in range(1, 11)]
    jobs = my.build_jobs(windows, 'fz2sx')
    assert [(j['target_reels'], j['reference_reels']) for j in jobs] == [(['FZ0003_010z1'], sx), (['FZ0003_010z2'], sx)]
    jobs = my.build_jobs(windows, 'sx2fz')  # 共用窗口的z1/z2合并成一个参考
    assert len(jobs) == 1
    assert jobs[0]['target_reels'] == sx
    assert jobs[0]['reference_reels'] == ['FZ0003_010z1', 'FZ0003_010z2']
    assert jobs[0]['z_reels'] == ['FZ0003_010z1', 'FZ0003_010z2']


def make_page(name, columns, center=()):
    """ columns: [(列序号, 文本)]，字cid在页内连续递增"""
    chars, cols, cid = [], [], 1
    for col_no, txt in columns:
        column_id = 'b1c%d' % col_no
        cols.append({'column_id': column_id, 'cid': col_no, 'is_center': col_no in center})
        for k, t in enumerate(txt, 1):
            chars.append({'char_id': '%sc%d' % (column_id, k), 'cid': cid, 'txt': t})
            cid += 1
    return {'name': name, 'chars': chars, 'columns': cols}


def texts(picked, vdict=None):
    return [my.page_text(s['page'], s['idx'], vdict or {})[0] for s in picked]


def test_select_by_e_format_column_and_char_range():
    page = make_page('SX_1_10_78', [(1, '正文正文'), (2, '音释甲乙'), (3, '正文丙丁'), (4, '版心版心')], center=(4,))
    # 第2列整列E；第3列第3、4个字（cid 11,12）为E字格式，其中单字格式起始值为空
    reel = {'reel_code': 'SX0001_010', 'reel_type': '', 'format': [
        {'name': 'SX_1_10_78', 'columns': [['E', 2]], 'chars': [['E', 3, 11, 11], ['E', 3, None, 12]]}]}
    picked = my.select_reel_yinshi(reel, [page])
    assert [s['method'] for s in picked] == ['E']
    assert texts(picked) == ['音释甲乙\n丙丁']


def test_ordinary_reel_without_e_has_no_yinshi():
    page = make_page('SX_1_1_1', [(1, '正文正文')])
    assert my.select_reel_yinshi({'reel_code': 'SX0001_001', 'reel_type': '', 'format': []}, [page]) == []


def test_fz_z_reel_cuts_scripture_before_title():
    p1 = make_page('FZ_1_1_1', [(1, '經文經文'), (2, '經文經文')])  # 整页都是正文
    p2 = make_page('FZ_1_1_2', [(1, '經文經文'), (2, '放光般若波羅蜜經卷第十二重'), (3, '音釋甲乙'), (4, '版心版心')], center=(4,))
    p3 = make_page('FZ_1_1_3', [(1, '音釋丙丁'), (2, '音釋戊己')])
    reel = {'reel_code': 'FZ0002_012z1', 'reel_type': '音释', 'format': []}
    picked = my.select_reel_yinshi(reel, [p1, p2, p3])
    assert [s['page']['name'] for s in picked] == ['FZ_1_1_2', 'FZ_1_1_3']
    assert texts(picked) == ['音釋甲乙', '音釋丙丁\n音釋戊己']
    assert {s['method'] for s in picked} == {'title'}


def test_title_without_zhong_and_no_title_fallback_to_all():
    p = make_page('FZ_1_1_1', [(1, '經文經文'), (2, '放光般若波羅蜜經卷第十四'), (3, '音釋甲乙')])
    picked = my.select_reel_yinshi({'reel_code': 'FZ0002_014z1', 'reel_type': '音释', 'format': []}, [p])
    assert texts(picked) == ['音釋甲乙']
    p = make_page('FZ_1_1_1', [(1, '音釋甲乙'), (2, '音釋丙丁')])
    picked = my.select_reel_yinshi({'reel_code': 'FZ0002_013z1', 'reel_type': '音释', 'format': []}, [p])
    assert [s['method'] for s in picked] == ['all']
    assert texts(picked) == ['音釋甲乙\n音釋丙丁']


def test_sx_pure_yinshi_reel_takes_everything_except_center():
    p = make_page('SX_1_1_1', [(1, '音釋甲乙'), (2, '版心版心')], center=(2,))
    picked = my.select_reel_yinshi({'reel_code': 'SX0027_001z1', 'reel_type': '音释', 'format': []}, [p])
    assert texts(picked) == ['音釋甲乙']


def test_page_text_normalises_variants_and_keeps_one_char_per_box():
    page = make_page('FZ_1_1_1', [(1, 'ab'), (2, 'cd')])
    page['chars'][0]['txt'] = 'v100'  # 有对应正字
    page['chars'][1]['txt'] = 'v200n'  # 没有对应正字
    page['chars'][2]['txt'] = 'v300'  # 正字有多个字符，只取第一个
    page['chars'][3].pop('txt')
    text, ordered = my.page_text(page, {0, 1, 2, 3}, {'v100': '正', 'v300': 'fw'})
    assert text == '正■\nf■'
    assert len(text.replace('\n', '')) == len(ordered) == 4


def test_page_text_orders_columns_and_chars_by_id_not_list_order():
    page = make_page('FZ_1_1_1', [(1, 'ab'), (2, 'cd')])
    page['chars'].reverse()
    text, ordered = my.page_text(page, set(range(4)), {})
    assert text == 'ab\ncd'
