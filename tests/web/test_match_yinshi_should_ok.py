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


def test_render_page_view_marks_differences_per_column():
    page = make_page('FZ_1_1_1', [(1, '潜昨塩反'), (2, '天字')])
    ids = set(range(len(page['chars'])))
    cmp_by_idx = {0: '潛', 1: '昨', 2: '𥂁', 3: '反', 4: '■', 5: '■'}
    lines = my.render_page_view(page, {'idx': ids}, {}, cmp_by_idx)
    assert lines == ['b1c1  txt: 潜昨塩反', '      cmp: 潛昨𥂁反', '           ＾　＾　',
                     'b1c2  txt: 天字', '      cmp: ■■', '           ＾＾']


REF = '替上六中反詎音巨\n鬼反笇筭字鄔波上\n減反區區丘俱反庸\n第二卷不出字\n第五卷不出字\n'


def test_find_short_match_exact_and_across_lines():
    assert my.find_short_match('鬼反笇筭字', REF) == '鬼反笇筭字'
    # 匹配文本跨列时保留换行，字数(去掉换行)与被查找文本一致
    m = my.find_short_match('波上減反區區', REF)
    assert m == '波上\n減反區區'
    assert len(m.replace('\n', '')) == len('波上減反區區')


def test_find_short_match_tolerates_a_wrong_char():
    assert my.find_short_match('減反區■丘俱反庸', REF) == '減反區區丘俱反庸'


def test_find_short_match_rejects_ambiguous_and_missing():
    assert my.find_short_match('卷不出字', REF) == ''  # 出现两次，无法判断是哪一处
    assert my.find_short_match('鑿鑿鑿鑿鑿鑿', REF) == ''  # 没有相似的文本
    assert my.find_short_match('', REF) == ''
    assert my.find_short_match('足够长的文本却比参考还长', '短') == ''


SPANS = [(0, 8, 'SX_1_4_57', ['SX0001_004']), (9, 17, 'SX_1_4_58', ['SX0001_004']),
         (18, 26, 'SX_1_5_1', ['SX0001_004', 'SX0001_005'])]
SPAN_REF = '替上六中反詎音巨\n鬼反笇筭字鄔波上\n減反區區丘俱反庸'


def test_locate_source_finds_pages_spanning_the_match():
    hit, note = my.locate_source(SPAN_REF, SPANS, '鬼反笇筭字鄔波上\n減反區')  # 跨第2、3页
    assert [n for n, _ in hit] == ['SX_1_4_58', 'SX_1_5_1']
    assert my._source_fields(hit) == {'source_reels': 'SX0001_004,SX0001_005', 'source_pages': 'SX_1_4_58,SX_1_5_1'}
    assert note == ''
    hit, _ = my.locate_source(SPAN_REF, SPANS, '替上六中反')
    assert [n for n, _ in hit] == ['SX_1_4_57']


def test_locate_source_falls_back_to_fuzzy_and_reports_failure():
    hit, note = my.locate_source(SPAN_REF, SPANS, '鬼反笇■字鄔波上')  # 含■，不能原样找到
    assert [n for n, _ in hit] == ['SX_1_4_58'] and 'fuzzy' in note
    assert my.locate_source(SPAN_REF, SPANS, '')[0] == []
    assert my.locate_source(SPAN_REF, SPANS, '鑿鑿鑿鑿鑿鑿鑿鑿')[1] == 'source not located'


def test_summarize_sutras_counts_status_rates_and_review_pages():
    rows = [
        {'sutra': 'FZ0002', 'job': 'FZ0002_010z1', 'reference': 'SX0002_001..010', 'page': 'p1', 'n_chars': 100,
         'status': 5, 'r_hit2base': 1.0, 'r_similar2hit': 1.0, 'n_same': 100, 'n_placeholder': 0, 'n_diff': 0},
        {'sutra': 'FZ0002', 'job': 'FZ0002_010z1', 'reference': 'SX0002_001..010', 'page': 'p2', 'n_chars': 50,
         'status': 3, 'r_hit2base': 0.8, 'r_similar2hit': 0.9, 'n_same': 30, 'n_placeholder': 10, 'n_diff': 10},
        {'sutra': 'FZ0002', 'job': 'FZ0002_010z1', 'page': 'p3', 'n_chars': 8, 'status': 2, 'r_hit2base': 0.1,
         'r_similar2hit': 0.2},
        {'sutra': 'FZ0002', 'job': 'FZ0002_011z1', 'page': 'p4', 'n_chars': 0, 'action': 'skipped_empty'},
        {'sutra': 'FZ0003', 'job': 'FZ0003_010z1', 'page': 'q1', 'n_chars': 20, 'status': 4, 'r_hit2base': 0.95,
         'r_similar2hit': 0.95, 'n_same': 19, 'n_placeholder': 0, 'n_diff': 1},
        {'job': 'FZ0009_001z1', 'action': 'no_reference'},  # 没有sutra的行忽略
    ]
    s = {r['sutra']: r for r in my.summarize_sutras(rows)}
    assert set(s) == {'FZ0002', 'FZ0003'}
    a = s['FZ0002']
    assert (a['pages'], a['status_5'], a['status_3'], a['status_2'], a['no_status']) == (4, 1, 1, 1, 1)
    assert a['jobs'] == 'FZ0002_010z1,FZ0002_011z1'
    assert a['avg_hit2base'] == round((1.0 + 0.8 + 0.1) / 3, 3)
    assert (a['same'], a['placeholder'], a['diff']) == (130, 10, 10) and a['pct_same'] == 86.7
    assert a['review_pages'] == 'p3,p4'  # 状态低于3或没有状态的页
    assert s['FZ0003']['review_pages'] == ''
    # 没有产生页的任务(目标或参考没有音释文本)在汇总里单独列出
    rows2 = rows[:1] + [{'sutra': 'FZ0002', 'job': 'FZ0002_020z1', 'action': 'no_target'},
                        {'sutra': 'FZ0002', 'job': 'FZ0002_030z1', 'action': 'no_reference'}]
    assert my.summarize_sutras(rows2)[0]['empty_jobs'] == 'FZ0002_020z1(no_target),FZ0002_030z1(no_reference)'
    assert my.summarize_sutras(rows2)[0]['pages'] == 1


def test_cmp_changes_only_reports_real_new_values():
    page = {'chars': [{'cmp_txt': '潛'}, {'cmp_txt': '■'}, {}, {'cmp_txt': '反'}]}
    ordered = [0, 1, 2, 3]
    proxies = [{'cmp_txt': '潜'}, {'cmp_txt': '昨'}, {'cmp_txt': '■'}, {'cmp_txt': None}]
    # 新值与原值相同的不算；新值为空的不会清掉已有内容
    assert my._cmp_changes(page, ordered, proxies) == {0: '潜', 1: '昨', 2: '■'}


def test_z1_z2_share_the_sx_yinshi_reel_listed_on_only_one_of_them():
    # 表里只有z1行带思溪藏自己的音释卷；z2必须也用它，否则sx2fz会把同一批思溪藏页分成两个任务重复匹配
    rows = [('FZ0033_001x1', 'SX0027_001x1'), ('FZ0033_001', 'SX0027_001'),
            ('FZ0033_001z1', 'SX0027_001z1'), ('FZ0033_001z2', None)]
    windows, _ = my.build_yinshi_windows(rows, {'FZ0033_001z1': '音释', 'FZ0033_001z2': '音释'})
    sx = ['SX0027_001x1', 'SX0027_001', 'SX0027_001z1']
    assert windows['FZ0033_001z1']['sx_reels'] == sx and windows['FZ0033_001z2']['sx_reels'] == sx
    jobs = my.build_jobs(windows, 'sx2fz')
    assert len(jobs) == 1 and jobs[0]['target_reels'] == sx
    assert jobs[0]['reference_reels'] == ['FZ0033_001z1', 'FZ0033_001z2']
    # 只有z1存在于库里时不受影响
    windows, _ = my.build_yinshi_windows(rows, {'FZ0033_001z1': '音释'})
    assert windows['FZ0033_001z1']['sx_reels'] == sx


def test_leftover_segments_and_assemble_keep_target_order():
    cmps = ['甲', '乙', '■', '■', None, '丙']
    segs = my.leftover_segments(cmps)
    assert segs == [(False, 0, 2), (True, 2, 5), (False, 5, 6)]
    assert my.assemble_match_txt(cmps, segs, []) == '甲乙\n丙'  # 没补找到的字略去
    assert my.assemble_match_txt(cmps, segs, [(2, 5, '丁戊己')]) == '甲乙\n丁戊己\n丙'  # 补找到的按目标字的位置放回


def test_leftover_candidates_start_and_end_on_column_boundaries_longest_first():
    cols = ['c1'] * 4 + ['c2'] * 12 + ['c3'] * 11  # 字0-3在第1列，4-15在第2列，16-26在第3列
    cands = my.leftover_candidates(cols, 2, 27)
    assert cands[0] == (2, 27)  # 整段最先
    assert (4, 27) in cands and (4, 16) in cands and (16, 27) in cands
    assert all(y - x >= my.LEFTOVER_MIN_LEN for x, y in cands)
    assert (2, 4) not in cands and (2, 16) in cands
    assert [y - x for x, y in cands] == sorted((y - x for x, y in cands), reverse=True)


# FZ1280：思溪藏页是A块在前、B块在后，福州藏页里B块在标题前、A块在后
SX_A = ['狹𬾃夾反俓直上古定反靣𤿥下側瘦反皮蹙也𮊵弱上力垂反', '下音若喘息上尺軟反泯絶上免忍反迅捷上私閏反下慈𫟒反詮', '七全反倉廪下吕錦反雲翳一反計障馭音御']
SX_B = ['求𠣏下音蓋乞也財賄下呼毎反顒忘恭反耆年上渠夷反老也', '衰邁上所追反下莫敗反']
FZ_B = ['求𠣏下音蓋乞也財賄下呼毎反顒愚恭反耆年上渠夷反老也', '𮕱邁上所追反下莫敗反']
FZ_A = ['狹𬾃夾反俓直上古定反靣𤿥下側瘦反皮蹙也𮊵弱上力垂反', '下音若喘息上尺軟反泯絶上免忍反迅捷上私閏反下慈𫟒反詮',
        '七全反倉廪下吕錦反糧斛上音良丨食下胡谷反丨斗雲翳下計', '反丨障馭音御']


def test_match_target_finds_the_chunk_that_is_in_a_different_order():
    page = make_page('SX_510_10_90', list(enumerate(SX_A + SX_B, 1)))
    t = {'page': page, 'idx': set(range(len(page['chars']))), 'methods': {'E'}}
    ref = '\n'.join(FZ_B + ['決定義經'] + FZ_A)
    spans = [(0, len(ref), 'FZ_1279_1_27', ['FZ1280_001z1'])]
    row, log = my._match_target('FZ1280_001z1', 'SX_510_10_90', t, ref, {}, 'fz_yinshi_scoped', ['FZ1280_001z1'],
                                spans=spans)
    n_b = sum(len(x) for x in SX_B)
    assert row['leftover_chars'] >= n_b and log['leftover_chars'] == row['leftover_chars']
    assert row['status'] >= 4 and row['r_hit2base'] > 0.9  # 只做首次匹配时是status 3、0.577
    assert row['source_pages'] == 'FZ_1279_1_27' and 'leftover pass' in row['note']
    # B块的字这次都有对应的字，不再是■
    status, ordered, proxies = my._fill_cmp(page, t, 'fz_yinshi_scoped', {}, log=log)
    tail = [p['cmp_txt'] for p in proxies][-n_b:]
    assert status == 'ok' and '■' not in tail and ''.join(tail) == ''.join(FZ_B)


def test_match_target_without_leftover_is_unchanged():
    page = make_page('SX_510_10_90', list(enumerate(SX_A + SX_B, 1)))
    t = {'page': page, 'idx': set(range(len(page['chars']))), 'methods': {'E'}}
    ref = '\n'.join(['決定義經'] + FZ_A + FZ_B)  # 顺序一致
    row, log = my._match_target('FZ1280_001z1', 'SX_510_10_90', t, ref, {}, 'fz_yinshi_scoped', ['FZ1280_001z1'])
    assert 'leftover_chars' not in row and 'leftover_chars' not in log


def page_with_cbeta_match(status=3, hit=120, similar=110):
    """ 整页200字，cbeta匹配只命中了正文；另有一条本工具写的音释日志(index_id相同的不算“之前”)"""
    prev = {'index_id': 'jsz-ik', 'status': status, 'len_base_txt': 200, 'len_hit': hit, 'len_similar': similar,
            'len_match_txt': hit, 'r_hit2base': hit / 200, 'r_similar2base': similar / 200}
    own = {'index_id': 'fz_yinshi_scoped', 'status': 5, 'len_hit': 999, 'len_similar': 999, 'len_match_txt': 999}
    return {'name': 'SX_1_1_1', 'match_logs': [prev, own], 'match': prev, 'base_txt': '正文' * 100, 'chars': [], 'columns': []}


def test_page_match_change_adds_yinshi_hits_to_the_whole_page():
    page = page_with_cbeta_match()  # 整页：命中120、相似110，状态3
    log = {'len_hit': 70, 'len_similar': 68, 'len_match_txt': 70}
    r = my.page_match_change(page, 'fz_yinshi_scoped', log, applied=True)
    assert (r['page_status_before'], r['page_status_after'], r['page_change']) == (3, 4, 'improved')
    assert (r['page_r_hit_before'], r['page_r_hit_after']) == (0.6, 0.95)  # 190/200
    assert r['page_r_similar_after'] == 0.89 and r['page_chars'] == 200 and r['page_match_from'] == 'jsz-ik'


def test_page_match_change_not_applied_or_no_earlier_match():
    log = {'len_hit': 70, 'len_similar': 68, 'len_match_txt': 70}
    r = my.page_match_change(page_with_cbeta_match(), 'fz_yinshi_scoped', log, applied=False)
    assert (r['page_status_before'], r['page_status_after'], r['page_change']) == (3, 3, 'not applied')
    # 整页原来没有匹配：之前为空，之后只有音释字的命中，占整页的比例低，仍是status 2
    page = {'name': 'FZ_1_1_1', 'match_logs': [], 'chars': [], 'columns': []}
    page['chars'] = [{'char_id': 'b1c1c%d' % k, 'cid': k, 'txt': '字'} for k in range(1, 101)]
    page['columns'] = [{'column_id': 'b1c1', 'cid': 1}]
    r = my.page_match_change(page, 'sx_yinshi_scoped', {'len_hit': 40, 'len_similar': 38, 'len_match_txt': 40}, True)
    assert r['page_status_before'] == '' and r['page_status_after'] == 2 and r['page_chars'] == 100
    assert r['page_r_hit_after'] == 0.4


def test_page_match_change_never_makes_the_page_worse_and_caps_at_page_size():
    # 原来状态5(全命中)：不管音释日志怎么算，之后不会更差，命中数不超过整页字数
    page = page_with_cbeta_match(status=5, hit=200, similar=200)
    r = my.page_match_change(page, 'fz_yinshi_scoped', {'len_hit': 50, 'len_similar': 30, 'len_match_txt': 50}, True)
    assert r['page_status_after'] == 5 and r['page_r_hit_after'] == 1.0 and r['page_change'] == 'same status'


def test_page_status_summary_counts_before_and_after():
    rows = [{'page_change': 'improved', 'page_status_before': 3, 'page_status_after': 4,
             'page_r_similar_before': 0.5, 'page_r_similar_after': 0.9},
            {'page_change': 'same status', 'page_status_before': 4, 'page_status_after': 4,
             'page_r_similar_before': 0.9, 'page_r_similar_after': 0.9},
            {'page_change': 'improved', 'page_status_before': '', 'page_status_after': 3,
             'page_r_similar_before': '', 'page_r_similar_after': 0.6},
            {'page': 'no comparison for this row'}]
    before, after, improved, total, avg_b, avg_a, applied = my.page_status_summary(rows)
    assert (before, after, improved, total, applied) == ('4:1 3:1 -:1', '4:2 3:1', 2, 3, 3)
    assert (avg_b, avg_a) == (0.467, 0.8)
    rows.append({'page_change': 'not applied', 'page_status_before': 2, 'page_status_after': 2,
                 'page_r_similar_before': 0.1, 'page_r_similar_after': 0.1})
    assert my.page_status_summary(rows)[3:7:3] == (4, 3)  # 4页参与统计，其中3页会填入cmp_txt


def test_make_run_flag_is_date_plus_three_digit_sequence():
    from datetime import datetime
    day = datetime(2026, 9, 21)
    assert my.make_run_flag(day) == 21092026001
    assert my.make_run_flag(day, 21092026001) == 21092026002
    assert my.make_run_flag(day, 21092026009) == 21092026010
    assert my.make_run_flag(day, 20260206002) == 21092026001  # 别的日期或别的格式的标记不影响今天的序号
    assert my.make_run_flag(datetime(2026, 9, 1)) == 1092026001  # 日期开头的0不保留，也不会与其它日期混淆
    try:
        my.make_run_flag(day, 21092026999)
        assert False
    except ValueError:
        pass


def test_page_match_change_ignores_the_length_of_an_unrelated_earlier_match_text():
    # 整页原来的匹配(状态2)找到的是一段不相干的文本，长度是整页的1.3倍；音释匹配命中了近九成。
    # 把两段匹配文本的长度相加会是2.2倍，被当成“匹配文本太长”而仍是状态2
    prev = {'index_id': 'jsz-ik', 'status': 2, 'len_base_txt': 200, 'len_hit': 20, 'len_similar': 8,
            'len_match_txt': 260, 'r_hit2base': 0.1, 'r_similar2base': 0.04, 'r_match2base': 1.3}
    page = {'name': 'SX_1_1_1', 'match_logs': [prev], 'match': prev, 'base_txt': '字' * 200, 'chars': [], 'columns': []}
    r = my.page_match_change(page, 'fz_yinshi_scoped', {'len_hit': 180, 'len_similar': 176, 'len_match_txt': 185}, True)
    assert (r['page_status_before'], r['page_status_after'], r['page_change']) == (2, 4, 'improved')
    assert r['page_r_hit_after'] == 1.0 and r['page_r_similar_after'] == 0.92
