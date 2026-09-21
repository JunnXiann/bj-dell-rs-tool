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


def test_status_flag_is_date_plus_the_whole_page_status_after_yinshi():
    date = my.flag_date_prefix('20260921')
    assert date == 20260921
    assert [my.status_flag(date, k) for k in range(6)] == [20260921000, 20260921001, 20260921002, 20260921003,
                                                          20260921004, 20260921005]
    assert my.status_flag(date, '') == my.status_flag(date, None) == 20260921002  # 算不出状态时按2(无匹配)
    assert len(str(my.flag_date_prefix())) == 8  # 不指定就是今天
    for bad in ('2026-09-21', '20261321', 'abc'):
        try:
            my.flag_date_prefix(bad)
            assert False, bad
        except ValueError:
            pass


def test_page_with_no_earlier_whole_page_match_is_recalculated_from_the_yinshi_match():
    page = {'name': 'SX_9_9_9', 'match_logs': [], 'chars': [], 'columns': [], 'base_txt': '字' * 100}
    page['chars'] = [{'char_id': 'b1c1c%d' % k, 'cid': k, 'txt': '字'} for k in range(1, 101)]
    page['columns'] = [{'column_id': 'b1c1', 'cid': 1}]
    log = {'len_hit': 96, 'len_similar': 95, 'len_match_txt': 98}
    r = my.page_match_change(page, 'fz_yinshi_scoped', log, applied=True)
    assert (r['page_status_before'], r['page_status_after']) == ('', 4)
    # 音释匹配不够好、没填入cmp_txt时，仍按它重新算状态(它是这页现在唯一的匹配)，报告里标“not applied”
    weak = {'len_hit': 30, 'len_similar': 20, 'len_match_txt': 40}
    r = my.page_match_change(page, 'fz_yinshi_scoped', weak, applied=False)
    assert r['page_status_before'] == '' and r['page_status_after'] == 2 and r['page_change'] == 'not applied'
    assert my.status_flag(20260921, r['page_status_after']) == 20260921002


def test_page_match_change_ignores_the_length_of_an_unrelated_earlier_match_text():
    # 整页原来的匹配(状态2)找到的是一段不相干的文本，长度是整页的1.3倍；音释匹配命中了近九成。
    # 把两段匹配文本的长度相加会是2.2倍，被当成“匹配文本太长”而仍是状态2
    prev = {'index_id': 'jsz-ik', 'status': 2, 'len_base_txt': 200, 'len_hit': 20, 'len_similar': 8,
            'len_match_txt': 260, 'r_hit2base': 0.1, 'r_similar2base': 0.04, 'r_match2base': 1.3}
    page = {'name': 'SX_1_1_1', 'match_logs': [prev], 'match': prev, 'base_txt': '字' * 200, 'chars': [], 'columns': []}
    r = my.page_match_change(page, 'fz_yinshi_scoped', {'len_hit': 180, 'len_similar': 176, 'len_match_txt': 185}, True)
    assert (r['page_status_before'], r['page_status_after'], r['page_change']) == (2, 4, 'improved')
    assert r['page_r_hit_after'] == 1.0 and r['page_r_similar_after'] == 0.92


def test_has_e_format_looks_at_columns_and_chars():
    assert my.has_e_format({'columns': [['E', 2]], 'chars': []})
    assert my.has_e_format({'columns': [], 'chars': [['E', 3, None, 12]]})
    assert not my.has_e_format({'columns': [['C', 1], ['G', 2]], 'chars': [['N', 1, 2, 3]]})
    assert not my.has_e_format({'columns': [], 'chars': []}) and not my.has_e_format({})


class FlagFakeDb:
    """ reel/page两个集合的极简替身，只支持flag_e用到的查询"""
    def __init__(self, reels, pages):
        import re
        outer = self
        outer.reel_docs, outer.page_docs = reels, pages

        class Reel:
            def find(self, cond, proj=None):
                rx = cond.get('reel_code', {}).get('$regex')
                return [r for r in outer.reel_docs if r.get('format') and (not rx or re.search(rx, r['reel_code']))]

        class Page:
            def find(self, cond, proj=None):
                return [dict(p) for p in outer.page_docs if p['name'] in cond['name']['$in']]

            def update_many(self, cond, upd):
                for p in outer.page_docs:
                    if p['name'] in cond['name']['$in'] and all(p.get(k) == v for k, v in cond.items() if k != 'name'):
                        p.update(upd.get('$set', {}))
                        for k in upd.get('$unset', {}):
                            p.pop(k, None)
        self.reel, self.page = Reel(), Page()


def flag_e_fixture():
    reels = [
        {'reel_code': 'SX0001_010', 'format': [
            {'name': 'SX_1_10_78', 'columns': [['E', 2]], 'chars': []},
            {'name': 'SX_1_10_79', 'columns': [['C', 1]], 'chars': []},  # 没有E
            {'name': 'SX_1_10_80', 'columns': [], 'chars': [['E', 3, None, 12]]}]},
        {'reel_code': 'SX0001_011', 'format': [{'name': 'SX_1_10_80', 'columns': [['E', 1]], 'chars': []}]},  # 共用页
        {'reel_code': 'FZ0002_012z1', 'format': [{'name': 'FZ_2_1_2', 'columns': [['E', 5]], 'chars': []},
                                                 {'name': 'FZ_2_1_9', 'columns': [['E', 1]], 'chars': []}]},
        {'reel_code': 'SX0001_012', 'format': []},
    ]
    pages = [{'name': 'SX_1_10_78', 'flag1': 91220251}, {'name': 'SX_1_10_79'}, {'name': 'SX_1_10_80'},
             {'name': 'FZ_2_1_2', 'flag1': 20260921111}]  # FZ_2_1_9没有页数据
    return reels, pages


def run_flag_e_on_fake(monkeypatch_db, value=20260921111, **kw):
    import helper
    saved = helper.get_db, helper.set_logging
    helper.get_db, helper.set_logging = (lambda db_id: monkeypatch_db), (lambda *a, **k: None)
    try:
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            my.run_flag_e(value=value, report_dir=d, **kw)
            import csv, glob
            return list(csv.DictReader(open(glob.glob(d + '/flag_e-*.csv')[0], encoding='utf-8-sig')))
    finally:
        helper.get_db, helper.set_logging = saved


def test_flag_e_dry_run_reports_and_writes_nothing():
    db = FlagFakeDb(*flag_e_fixture())
    rows = {r['page']: r for r in run_flag_e_on_fake(db, reel_regex='')}  # 空=所有藏
    assert set(rows) == {'SX_1_10_78', 'SX_1_10_80', 'FZ_2_1_2', 'FZ_2_1_9'}  # 没有E的SX_1_10_79不在里面
    assert rows['SX_1_10_80']['reels'] == 'SX0001_010,SX0001_011'  # 共用页只出现一次，列出两个卷
    assert (rows['SX_1_10_78']['action'], rows['SX_1_10_78']['prev_flag']) == ('dry_run', '91220251')
    assert rows['FZ_2_1_2']['action'] == 'already_set' and rows['FZ_2_1_9']['action'] == 'no_page'
    assert [p.get('flag1') for p in db.page_docs] == [91220251, None, None, 20260921111]


def test_flag_e_commit_overwrites_or_keeps_existing_and_can_filter_reels():
    db = FlagFakeDb(*flag_e_fixture())
    run_flag_e_on_fake(db, commit=True, keep_existing=True, reel_regex='')
    assert [p.get('flag1') for p in db.page_docs] == [91220251, None, 20260921111, 20260921111]
    db = FlagFakeDb(*flag_e_fixture())
    rows = run_flag_e_on_fake(db, commit=True, reel_regex='')  # 不加keep_existing：覆盖别的批次标记
    assert [p.get('flag1') for p in db.page_docs] == [20260921111, None, 20260921111, 20260921111]
    assert {r['action'] for r in rows} == {'written', 'already_set', 'no_page'}
    db = FlagFakeDb(*flag_e_fixture())
    rows = run_flag_e_on_fake(db, commit=True, reel_regex='^SX')  # 只看SX的卷
    assert {r['page'] for r in rows} == {'SX_1_10_78', 'SX_1_10_80'}
    assert db.page_docs[3]['flag1'] == 20260921111 and db.page_docs[0]['flag1'] == 20260921111


def test_flag_e_not_flag3_date_marks_only_the_pages_match_and_apply_did_not_touch():
    reels, pages = flag_e_fixture()
    for p in pages:
        if p['name'] == 'SX_1_10_78':
            p['flag3'] = 20260921003  # 今天match/apply处理过(整页状态3)
        if p['name'] == 'SX_1_10_80':
            p['flag3'] = 2606260924  # 别的批次的标记，不在今天的000-005里
    db = FlagFakeDb(reels, pages)
    rows = {r['page']: r for r in run_flag_e_on_fake(db, value=20260921112, commit=True, not_flag3_date='20260921',
                                                     reel_regex='')}
    assert rows['SX_1_10_78']['action'] == 'skipped_touched' and rows['SX_1_10_78']['flag3'] == '20260921003'
    assert rows['SX_1_10_80']['action'] == 'written' and rows['FZ_2_1_2']['action'] == 'written'
    assert [p.get('flag1') for p in db.page_docs] == [91220251, None, 20260921112, 20260921112]  # 被跳过的页flag1不动
    assert db.page_docs[2]['flag3'] == 2606260924  # 不改flag3
    # 日期范围的边界：000和005算处理过，006和昨天的不算
    reels, pages = flag_e_fixture()
    pages[0]['flag3'], pages[2]['flag3'], pages[3]['flag3'] = 20260921000, 20260921005, 20260921006
    rows = {r['page']: r['action'] for r in run_flag_e_on_fake(FlagFakeDb(reels, pages), value=1, reel_regex='',
                                                               not_flag3_date=20260921)}
    assert rows['SX_1_10_78'] == rows['SX_1_10_80'] == 'skipped_touched' and rows['FZ_2_1_2'] == 'dry_run'
    try:
        run_flag_e_on_fake(FlagFakeDb(*flag_e_fixture()), value=1, not_flag3_date='2026-09-21')
        assert False
    except ValueError:
        pass


def test_flag_e_only_touches_sx_pages_by_default():
    db = FlagFakeDb(*flag_e_fixture())
    rows = run_flag_e_on_fake(db, value=20260921112, commit=True)  # 不指定reel_regex
    assert {r['page'] for r in rows} == {'SX_1_10_78', 'SX_1_10_80'}  # 福州藏的FZ_2_1_2、FZ_2_1_9不在报告里
    fz = [p for p in db.page_docs if p['name'].startswith('FZ_')]
    assert fz and all(p.get('flag1') == 20260921111 for p in fz)  # 福州藏的页一个字段都没动
    assert [p.get('flag1') for p in db.page_docs if p['name'].startswith('SX_')] == [20260921112, None, 20260921112]
    for code in ('SX0001_010', 'SX0027_001z1'):
        assert __import__('re').search(my.SX_REEL_REGEX, code)
    assert not __import__('re').search(my.SX_REEL_REGEX, 'FZ0002_012z1')


def test_flag_e_refuses_the_plain_flag_field():
    # 平台用flag(无数字)选页，如flag=717；--field=flag曾经把它覆盖掉
    db = FlagFakeDb(*flag_e_fixture())
    for bad in ('flag', 'flags', 'cmp_txt', ''):
        try:
            run_flag_e_on_fake(db, field=bad, commit=True)
            assert False, bad
        except ValueError:
            pass
    assert [p.get('flag1') for p in db.page_docs] == [91220251, None, None, 20260921111]
    run_flag_e_on_fake(FlagFakeDb(*flag_e_fixture()), field='flag3')  # flag3、flag2这类可以


def test_flag_e_undo_restores_previous_values_exactly_and_leaves_changed_pages():
    import csv, glob, helper, tempfile
    reels, _ = flag_e_fixture()
    pages = [{'name': 'SX_1_10_78', 'flag1': 91220251}, {'name': 'SX_1_10_79', 'flag1': 7},
             {'name': 'SX_1_10_80'}, {'name': 'FZ_2_1_2', 'flag1': 25674}]
    db = FlagFakeDb(reels, pages)
    saved = helper.get_db, helper.set_logging
    helper.get_db, helper.set_logging = (lambda db_id: db), (lambda *a, **k: None)
    try:
        with tempfile.TemporaryDirectory() as d:
            my.run_flag_e(value=20260921111, reel_regex='', commit=True, report_dir=d)  # 误把所有藏都打了标记
            report = glob.glob(d + '/flag_e-*.csv')[0]
            assert [p.get('flag1') for p in db.page_docs] == [20260921111, 7, 20260921111, 20260921111]
            db.page_docs[3]['flag1'] = 999  # FZ_2_1_2之后被别的操作改过
            # 预演：不写库
            my.run_flag_e_undo(report=report, field='flag1', value=20260921111, report_dir=d)
            assert [p.get('flag1') for p in db.page_docs] == [20260921111, 7, 20260921111, 999]
            my.run_flag_e_undo(report=report, field='flag1', value=20260921111, commit=True, report_dir=d)
            rows = {r['page']: r for r in csv.DictReader(open(glob.glob(d + '/flag_e_undo-*.csv')[-1], encoding='utf-8-sig'))}
    finally:
        helper.get_db, helper.set_logging = saved
    assert db.page_docs[0]['flag1'] == 91220251 and isinstance(db.page_docs[0]['flag1'], int)  # 原值(整数)还原
    assert 'flag1' not in db.page_docs[2]  # 原来没有这个字段：删掉，而不是留下空值
    assert db.page_docs[3]['flag1'] == 999  # 之后被改过的页不动
    assert db.page_docs[1]['flag1'] == 7  # 没有E格式的页从头到尾没碰过
    assert {k: v['action'] for k, v in rows.items()} == {'SX_1_10_78': 'restored', 'SX_1_10_80': 'restored',
                                                          'FZ_2_1_2': 'skipped_changed'}


def test_flag_e_undo_of_a_dry_run_report_does_nothing():
    import glob, helper, tempfile
    db = FlagFakeDb(*flag_e_fixture())
    saved = helper.get_db, helper.set_logging
    helper.get_db, helper.set_logging = (lambda db_id: db), (lambda *a, **k: None)
    try:
        with tempfile.TemporaryDirectory() as d:
            my.run_flag_e(value=20260921111, reel_regex='', report_dir=d)  # 预演，报告里没有written
            before = [dict(p) for p in db.page_docs]
            my.run_flag_e_undo(report=glob.glob(d + '/flag_e-*.csv')[0], field='flag1', value=20260921111, commit=True,
                               report_dir=d)
    finally:
        helper.get_db, helper.set_logging = saved
    assert db.page_docs == before


def test_flag_e_undo_can_restore_the_plain_flag_field_but_not_arbitrary_fields():
    import csv, glob, helper, tempfile
    reels, _ = flag_e_fixture()
    # 误把plain flag改成了20260921112：三页原来的flag分别是717、404和没有
    pages = [{'name': 'SX_1_10_78', 'flag': 20260921112}, {'name': 'SX_1_10_80', 'flag': 20260921112},
             {'name': 'FZ_2_1_2', 'flag': 20260921112}]
    db = FlagFakeDb(reels, pages)
    saved = helper.get_db, helper.set_logging
    helper.get_db, helper.set_logging = (lambda db_id: db), (lambda *a, **k: None)
    try:
        with tempfile.TemporaryDirectory() as d:
            report = d + '/flag_e-x.csv'
            with open(report, 'w', encoding='utf-8-sig', newline='') as f:
                f.write('page,reels,prev_flag,flag3,action\nSX_1_10_78,SX0001_010,717,,written\n'
                        'SX_1_10_80,SX0001_010,404,,written\nFZ_2_1_2,FZ0002_012z1,,,written\n'
                        'SX_1_10_81,SX0001_010,5,,skipped_touched\n')
            my.run_flag_e_undo(report=report, field='flag', value=20260921112, commit=True, report_dir=d)
            for bad in ('cmp_txt', 'name', ''):
                try:
                    my.run_flag_e_undo(report=report, field=bad, value=1, report_dir=d)
                    assert False, bad
                except ValueError:
                    pass
    finally:
        helper.get_db, helper.set_logging = saved
    assert db.page_docs[0]['flag'] == 717 and db.page_docs[1]['flag'] == 404
    assert 'flag' not in db.page_docs[2]  # 原来没有值的页删掉字段
    # flag_e打标记时仍然拒绝plain flag
    try:
        my.check_flag_field('flag')
        assert False
    except ValueError:
        pass


def status_page(name, status=None, similar=0.5):
    """ 只带整页匹配的页：cbeta整页匹配，状态status(None=完全没有匹配)"""
    if status is None:
        return {'name': name, 'match_logs': [], 'base_txt': '正文' * 50}
    log = {'index_id': 'jsz-ik', 'status': status, 'len_base_txt': 100, 'r_hit2base': similar, 'r_similar2base': similar}
    return {'name': name, 'match_logs': [log], 'match': log, 'base_txt': '正文' * 50}


def page_status_fixture():
    """ 五页含E：a匹配后升级(preview报告里有)、b匹配了但不填、c在对照表里但没有匹配结果、d不在对照表、e库里没有"""
    epages = {'SX_1_1_1': ['SX0001_001'], 'SX_1_1_2': ['SX0001_001'], 'SX_1_1_3': ['SX0001_001'],
              'SX_2_1_1': ['SX0002_001'], 'SX_2_1_2': ['SX0002_001']}
    rows = [
        {'page': 'SX_1_1_1', 'status': 5, 'page_change': 'improved', 'page_status_before': 3, 'page_status_after': 4},
        {'page': 'SX_1_1_2', 'status': 2, 'page_change': 'not applied', 'page_status_before': 3, 'page_status_after': 3},
        {'page': 'SX_1_1_3', 'action': 'no_match_txt'},
        {'job': 'FZ0001_010z1', 'action': 'no_reference'},  # 没有页的行忽略
    ]
    docs = {'SX_1_1_3': status_page('SX_1_1_3', 4), 'SX_2_1_1': status_page('SX_2_1_1')}  # SX_2_1_2没有页数据
    return epages, rows, docs


def test_combine_page_status_covers_every_yinshi_page_not_just_the_matched_ones():
    table = {r['page']: r for r in my.combine_page_status(*page_status_fixture(), 'fz_yinshi_scoped')}
    assert list(table) == ['SX_1_1_1', 'SX_1_1_2', 'SX_1_1_3', 'SX_2_1_1', 'SX_2_1_2']
    assert [table[p]['coverage'] for p in table] == ['applied', 'not_applied', 'no_match', 'not_in_sheet', 'no_page']
    assert (table['SX_1_1_1']['page_status_before'], table['SX_1_1_1']['page_status_after']) == (3, 4)
    # 对照表范围内但没匹配结果：读库里原有的整页匹配，前后一样
    assert (table['SX_1_1_3']['page_status_before'], table['SX_1_1_3']['page_status_after'],
            table['SX_1_1_3']['note']) == (4, 4, 'no_match_txt')
    assert table['SX_1_1_3']['page_match_from'] == 'jsz-ik' and table['SX_1_1_3']['sutra'] == 'SX0001'
    # 不在对照表、原来完全没有整页匹配：状态为空('-')，前后都一样
    assert (table['SX_2_1_1']['page_status_before'], table['SX_2_1_1']['page_status_after']) == ('', '')
    assert 'page_change' not in table['SX_2_1_2']  # 库里没有的页不进前后分布


def test_unchanged_page_status_ignores_the_tools_own_earlier_log():
    page = status_page('SX_1_1_1', 3, 0.6)
    page['match_logs'].append({'index_id': 'fz_yinshi_scoped', 'status': 5, 'r_similar2base': 1.0})  # 上次match写的，不算
    r = my.unchanged_page_status(page, 'fz_yinshi_scoped')
    assert (r['page_status_before'], r['page_status_after'], r['page_change']) == (3, 3, 'unchanged')
    assert r['page_r_similar_before'] == 0.6 and r['page_chars'] == 100


def test_names_to_lookup_skips_pages_the_preview_already_compared():
    epages, rows, _ = page_status_fixture()
    assert my.names_to_lookup(epages, rows) == ['SX_1_1_3', 'SX_2_1_1', 'SX_2_1_2']


def test_status_transitions_and_summary_lines():
    table = my.combine_page_status(*page_status_fixture(), 'fz_yinshi_scoped')
    assert my.status_transitions(table) == {('3', '4'): 1, ('3', '3'): 1, ('4', '4'): 1, ('-', '-'): 1}
    head = '\n'.join(my.page_status_head(table, 'tw-prod-readonly', '^SX'))
    assert 'pages=5' in head and 'improved 1 pages' in head and '3 -> 4 : 1  (changed)' in head
    assert '- -> - : 1' in head and 'no_page' in head
    by = {r['sutra']: r for r in my.summarize_page_status_by_sutra(table)}
    assert by['SX0001']['pages'] == 3 and by['SX0001']['applied'] == 1 and by['SX0002']['not_in_sheet'] == 1


def test_run_page_status_from_a_preview_csv_reads_only_the_other_pages():
    import helper, glob, tempfile
    with tempfile.TemporaryDirectory() as tmp:
        check_run_page_status(tmp)


def check_run_page_status(tmp_path):
    import helper, glob
    tmp_path = __import__('pathlib').Path(tmp_path)
    epages, rows, docs = page_status_fixture()
    reels = [{'reel_code': 'SX0001_001', 'format': [{'name': n, 'columns': [['E', 1]], 'chars': []}
                                                    for n in ('SX_1_1_1', 'SX_1_1_2', 'SX_1_1_3')]},
             {'reel_code': 'SX0002_001', 'format': [{'name': n, 'columns': [['E', 1]], 'chars': []}
                                                    for n in ('SX_2_1_1', 'SX_2_1_2')]}]
    db = FlagFakeDb(reels, list(docs.values()))
    csv_path = str(tmp_path / 'pages.csv')
    my.write_csv(csv_path, rows, ['job', 'page', 'status', 'action'] + my.PAGE_MATCH_FIELDS)
    saved = helper.get_db, helper.set_logging
    helper.get_db, helper.set_logging = (lambda db_id: db), (lambda *a, **k: None)
    try:
        my.run_page_status(pages_csv=csv_path, report_dir=str(tmp_path))
    finally:
        helper.get_db, helper.set_logging = saved
    out = glob.glob(str(tmp_path / 'page_status-*'))[0]
    import csv as csvmod
    table = {r['page']: r for r in csvmod.DictReader(open(out + '/pages_all.csv', encoding='utf-8-sig'))}
    assert len(table) == 5 and table['SX_1_1_1']['coverage'] == 'applied'
    assert table['SX_1_1_1']['page_status_after'] == '4' and table['SX_2_1_1']['coverage'] == 'not_in_sheet'
    assert 'improved 1 pages' in open(out + '/summary.txt', encoding='utf-8').read()
