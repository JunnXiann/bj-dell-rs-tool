from util.find_match import find_best_match


def test_find_match_case1():
    # 测试查找径山藏第4卷的文本
    txt1 = open('tests/data/大般若经第四卷-JS_1_5卷文本.txt', 'r').read()
    txt2 = open('tests/data/大般若经-T0220(前10卷).txt', 'r').read()
    match_txt, stat = find_best_match(txt1, txt2)[:2]
    assert len(match_txt) >= len(txt1)
    assert stat['base']['match_ratio'] > 0.95
    # 测试 match_txt没有因为音释而引入噪音
    assert '大般若波羅蜜多經卷第四' in match_txt[-15:]

    # 测试查找JS_1_82页文本
    txt1 = open('tests/data/大般若经第四卷-JS_1_82页文本.txt', 'r').read()
    match_txt, stat = find_best_match(txt1, txt2)[:2]
    assert len(match_txt) >= len(txt1)
    assert stat['base']['match_ratio'] > 0.95

    # 测试查找SX_1_4_57页文本
    txt1 = open('tests/data/大般若经第四卷-SX_1_4_57页文本.txt', 'r').read()
    match_txt, stat = find_best_match(txt1, txt2)[:2]
    assert len(match_txt) >= len(txt1)
    assert stat['base']['match_ratio'] > 0.95

    # 测试从JS_1_82页文本中查找SX_1_4_57页文本
    txt1 = open('tests/data/大般若经第四卷-SX_1_4_57页文本.txt', 'r').read()
    txt2 = open('tests/data/大般若经第四卷-JS_1_82页文本.txt', 'r').read()
    match_txt, stat = find_best_match(txt1, txt2)[:2]
    assert len(match_txt) >= len(txt1)
    assert stat['base']['match_ratio'] > 0.95


def test_find_match_case2():
    # 测试顺序颠倒时，进行二次查找
    txt1 = open('tests/data/大般若经第四卷-JS_1_5卷文本人工颠倒.txt', 'r').read()
    txt2 = open('tests/data/大般若经第四卷-CBETA文本前后扩展.txt', 'r').read()
    match_txt, stat, refind_len = find_best_match(txt1, txt2)[:3]
    assert len(match_txt) >= len(txt1)
    assert stat['base']['match_ratio'] > 0.95
    assert refind_len > 0
