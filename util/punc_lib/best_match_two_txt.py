from rapidfuzz import fuzz
import re
import logging
import os
import sys
import string
from datetime import datetime, timezone, timedelta

root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(root_dir)
import helper as hp

# 单例模式初始化（防止重复配置）
if not logging.getLogger().hasHandlers():
    cur_time = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    hp.set_logging("find_best_match_text-" + str(cur_time), False)


class BestMatchTwoTxt:
    def __init__(self):
        pass

    """
    算法描述：
    需要找到文本一在文本二最大的文字匹配区间，文本一可能有几千字，文本二可能上10w字，其中文本一不一定跟最大文字匹配区间完全一样，会有部分文字差异；
    例子如下：

    文本一:
    時人問言：「汝何因緣爾？」答言：「我智慧多，恐腹裂故。」「汝頭上何以著火？」「欲照闇故。」語言：「癡婆羅門！日照天下，何以言闇？」答言：「汝等不知，闇有二種：一者無日月火燭，二者愚癡無智慧明。」諸人言：「汝未見訶哆釋子比丘，故敢作是語。若見共語者，日出則闇，夜則日出。」

    文本二：
    佛在舍衛國。爾時南天竺有論議師，以銅鍱鍱腹、頭上然火來入舍衛國。時人問言：「汝何因緣爾？」答言：「我智慧多裂故。」「汝頭上何以著火？」「欲照闇故。」語言：「癡婆羅門！日照天下，何以言闇？」答言：「汝等不知，闇有二種：一者無日月火燭，二者愚癡無智慧明。」諸人言：「汝未見訶哆釋子比丘，故敢作是語。随便写点字。若見共語者，日出則闇，夜則日出。」時城內人民即喚訶哆釋子比丘，欲令共論。時訶哆聞之心愁，不得已而來入城道中，見二羝羊共鬪，即因取相作是念：「一羊是婆羅門，一羊是我。」是我者鬪則不如，見已轉更愁憂。前行又見二牛共鬪，復作是念：「一牛是婆羅門，一牛是我。」是我者即復不如。又前行復見二人相撲，作是念：「一是婆羅門，一是我。」我者即復不如。欲入論處，見一女人持滿瓶水，水瓶即破，復作是念：「我見諸不吉相，將無不如。」不得已，便前入舍，見是論師婆羅門眼口相貌，自知不如愁憂更甚。適坐須臾，諸人便言：「可共論議。」答言：「我今小不安隐，須待明日。」作是語已便還宿處，至後夜時即向王舍城。明旦城中人集，久待不來，知時已過。自到祇桓推尋求之，餘比丘言：「訶哆釋子即後夜時持衣鉢去。」諸城內人聞已種種呵責：「云何名比丘故妄語？」一人語二人、二人語三人，如是展轉惡名流布滿舍衛城。是中有比丘少欲知足行頭陀，著衣持鉢入城乞食，聞是事心不喜，食已向佛廣說。佛以是事集比丘僧，以種種因緣呵責：「云何名比丘故妄語？」種種呵已語諸比丘：「以十利故與諸比丘結戒。從今是戒應如是說：若比丘故妄語者，波夜提。」

    输出最匹配的文本二的段落应该为：
    時人問言：「汝何因緣爾？」答言：「我智慧多裂故。」「汝頭上何以著火？」「欲照闇故。」語言：「癡婆羅門！日照天下，何以言闇？」答言：「汝等不知，闇有二種：一者無日月火燭，二者愚癡無智慧明。」諸人言：「汝未見訶哆釋子比丘，故敢作是語。随便写点字。若見共語者，日出則闇，夜則日出。」

    算法思路：
    目标：为了让匹配的段落尽可能短，同时又能最大程度匹配文本一
    具体思路：在找到最佳匹配窗口后，尝试从窗口的两端向内收缩，直到匹配率开始下降，以此来找到最短的匹配段落。
    """

    def find_best_match(self, text1, text2):
        len_text1 = len(text1)
        len_text2 = len(text2)
        # 去掉干扰字符
        text2 = re.sub(r"\[JS_\d+(_\d+)?\]", "", text2)

        # logging.info(f"find_best_match_start text1:\n{text1}, \n text2:\n{text2}\n")
        if len_text1 == 0 or len_text2 == 0:
            return "", "", "", 0.0

        # 去除标点
        text1_no_punc = self.remove_punctuation(text1)
        text2_no_punc = self.remove_punctuation(text2)

        text1_len = len(text1_no_punc)
        text2_len = len(text2_no_punc)
        logging.info(
            f"find_best_match start,text1_len: {text1_len}, text2_len: {text2_len}"
        )

        # 动态调整初始窗口大小（不超过文本二长度，步长的2倍盈余，确保窗口能覆盖text1）
        window_size = min(text1_len + 2 * text1_len // 10, text2_len)
        step = max(100, text1_len // 10)

        logging.info(
            f"window_size: {window_size}, step: {step},len_text1_no_punc: {text1_len},len_text2_no_punc: {text2_len}"
        )

        best_ratio = 0.0
        best_match = (0, 0)

        # 处理当文本二比窗口小时的情况
        if text2_len < window_size:
            logging.info(f"text2_len < window_size: {text2_len} < {window_size}")
            best_match = (0, text2_len)
        else:
            # 第一轮：粗粒度搜索
            limit_index = text2_len - window_size + 1
            for start in range(0, limit_index, step):
                end = start + window_size
                window = text2_no_punc[start:end]
                current_ratio = fuzz.ratio(text1_no_punc, window)
                # print(f"start: {start}, end: {end}, current_ratio: {current_ratio},best_ratio: {best_ratio}")
                if current_ratio > best_ratio:
                    best_ratio = current_ratio
                    best_match = (start, end)

                # 最后一组, 可能不足1个window_size，单独判断
                if start + step >= limit_index:
                    start = max(0, text2_len - window_size - 1)
                    end = text2_len
                    window = text2_no_punc[start:end]
                    current_ratio = fuzz.ratio(text1_no_punc, window)
                    # print(f"last_loop,start: {start}, end: {end}, current_ratio: {current_ratio},best_ratio: {best_ratio}")
                    if current_ratio > best_ratio:
                        best_ratio = current_ratio
                        best_match = (start, end)
                    break

        logging.info(f"第1轮粗搜 Best match: {best_match} with ratio: {best_ratio}")

        start, end = best_match
        # logging.info(f"第1轮粗搜内容：content:{text2_no_punc[start:end]}")

        # 双指针：尝试从两端收缩窗口以找到最短匹配
        def shrink_window(left, right):
            best_shrink_ratio = fuzz.ratio(text1_no_punc, text2_no_punc[left:right])
            best_shrink_match = (left, right)
            # 收缩左边界
            new_left = left
            # 保证基础长度
            while new_left < right:
                ratio = fuzz.ratio(text1_no_punc, text2_no_punc[new_left:right])
                if ratio >= best_shrink_ratio:
                    best_shrink_ratio = ratio
                    best_shrink_match = (new_left, right)
                    new_left += 1
                else:
                    break
            left = best_shrink_match[0]
            # 收缩右边界
            new_right = right
            while new_right > left:
                ratio = fuzz.ratio(text1_no_punc, text2_no_punc[left:new_right])
                if ratio >= best_shrink_ratio:
                    best_shrink_ratio = ratio
                    best_shrink_match = (left, new_right)
                    new_right -= 1
                else:
                    break
            return best_shrink_match, best_shrink_ratio

        # 二分法缩小窗口
        def shrink_window_bisect(text1_no_punc, text2_no_punc, start, end):
            def calc_ratio(l, r):
                if r - l < len(text1_no_punc):  # too small
                    return 0
                return fuzz.ratio(text1_no_punc, text2_no_punc[l:r])

            best_l, best_r = start, end
            best_ratio = calc_ratio(start, end)

            # Binary search to shrink left boundary
            l_lo, l_hi = start, end - len(text1_no_punc)
            while l_lo <= l_hi:
                mid_l = (l_lo + l_hi) // 2
                ratio = calc_ratio(mid_l, end)
                if ratio >= best_ratio:
                    best_ratio = ratio
                    best_l = mid_l
                    l_lo = mid_l + 1  # try shrinking more
                else:
                    l_hi = mid_l - 1

            # Binary search to shrink right boundary
            r_lo, r_hi = best_l + len(text1_no_punc), end
            while r_lo <= r_hi:
                mid_r = (r_lo + r_hi) // 2
                ratio = calc_ratio(best_l, mid_r)
                if ratio >= best_ratio:
                    best_ratio = ratio
                    best_r = mid_r
                    r_hi = mid_r - 1  # try shrinking more
                else:
                    r_lo = mid_r + 1

            return (best_l, best_r), best_ratio

        # 文字少的时候，直接用双指针，更加精准
        if end - start < 10000:
            logging.info(f"use shrink_window,size:{end - start}")
            method = "shrink_window"
        # 文字多的时候，用二分法，更快，牺牲一点精度
        else:
            logging.info(f"use shrink_window_bisect,size:{end - start}")
            method = "shrink_window_bisect"

        if method == "shrink":

            best_shrink_match, best_shrink_ratio = shrink_window(start, end)
            logging.info(
                f"第2轮缩小窗口,shrink_window best_shrink_match: {best_shrink_match},best_shrink_ratio: {best_shrink_ratio}"
            )
        else:

            best_shrink_match, best_shrink_ratio = shrink_window_bisect(
                text1_no_punc, text2_no_punc, start, end
            )

            # 往前后各加1000字，再双指针
            start = max(start - 1000, 0)
            end = min(end + 1000, len(text2_no_punc))
            logging.info(
                f"第2轮缩小窗口,先shrink_window_bisect best_shrink_match: {best_shrink_match},best_shrink_ratio: {best_shrink_ratio},new_start:{start},new_end:{end}"
            )
            best_shrink_match, best_shrink_ratio = shrink_window(start, end)
            logging.info(
                f"第2轮缩小窗口,再shrink_window best_shrink_match: {best_shrink_match},best_shrink_ratio: {best_shrink_ratio}"
            )

        start, end = best_shrink_match
        # logging.info(f"第2轮细搜内容：content:{text2_no_punc[start:end]}")

        # 找回原始文本2中对应的位置

        original_start = 0
        original_end = 0
        non_punc_index = 0
        for i in range(len(text2)):
            if self.remove_punctuation(text2[i]) != "":
                if non_punc_index == start:
                    original_start = i
                if non_punc_index == end - 1:
                    original_end = i + 1
                non_punc_index += 1

        # 定义左/右标点集合
        left_puncs = set("[{「『（<【《〔“‘")
        all_puncs = set(
            string.punctuation
            + "¶，。！？；：、（）“”‘’《》【】『』「」〔〕—…·．,.!?;:()[]{}<>\"'"
        )

        # 段首：只检查首字左侧第一个字符是否为左标点
        if original_start > 0 and text2[original_start - 1] in left_puncs:
            original_start -= 1

        # 段尾：拼接后续标点
        while (
            original_end < len(text2)
            and text2[original_end] in all_puncs
            and text2[original_end] not in left_puncs
        ):
            original_end += 1

        # 提取带标点的段落
        matched_paragraph = text2[original_start:original_end]
        matched_paragraph = self.remove_start_puncs(matched_paragraph)

        # 提取无标点的匹配段落
        matched_paragraph_no_punc = text2_no_punc[start:end]

        # logging.info(f"最终匹配原文: text1_no_punc：\n{text1_no_punc}")
        # logging.info(f"\n最终匹配结果: matched_paragraph_no_punc:\n{matched_paragraph_no_punc}")

        match_rate = fuzz.ratio(text1_no_punc, matched_paragraph_no_punc)
        match_rate = round(match_rate / 100, 4)

        logging.info(f"find_best_match end,最终匹配率：{match_rate}")
        return text1_no_punc, matched_paragraph_no_punc, matched_paragraph, match_rate

    def read_text_file(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as file:
                content = file.read()
                return content
        except FileNotFoundError:
            print(f"错误：未找到文件 {file_path}。")
        except Exception as e:
            print(f"发生未知错误：{e}")
        return None

    # 定义去除标点的函数
    def remove_punctuation(self, text):
        # 先去除标点符号
        punctuation_pattern = r"[^\w\s]"
        text = re.sub(punctuation_pattern, "", text)
        # 过滤JS_前缀数字格式
        text = re.sub(r"\[JS_\d+(_\d+)?\]", "", text)
        # 移除所有空白字符，包括全角空格
        text = re.sub(r"\s+", "", text)

        return text

    def remove_start_puncs(self, text):
        # 去掉段落开头的换行符和¶符号
        num = 0
        while text.startswith("\n") or text.startswith("¶"):
            text = text[1:]
            if num > 3:
                break
            num += 1
        return text

    def remove_base_txt_lines(self, text):
        lines = text.split("\n")
        new_lines = [
            line
            for line in lines
            if not (line.strip().startswith("[") and line.strip().endswith("]"))
        ]
        return "\n".join(new_lines)

    def remove_cmp_txt_lines(self, text):

        lines = text.split("\n")
        new_lines = [line for line in lines if not line.strip().startswith("#")]
        return "\n".join(new_lines)


if __name__ == "__main__":
    BestMatch = BestMatchTwoTxt()
    # 读取本地测试数据
    test_jsz = "JS_1319_6"
    test_cbeta = "T0212"

    test_jsz = "JS_2024_3"
    test_cbeta = "JB351"

    test_jsz = "JS_1118_8"
    test_cbeta = "T1435"

    test_jsz = "JS_1118_8_test"
    test_cbeta = "T1435_test"

    text1 = BestMatch.read_text_file(f"web/tr/punc_trans/test_datas/{test_jsz}.txt")
    text2 = BestMatch.read_text_file(f"web/tr/punc_trans/test_datas/{test_cbeta}.txt")
    print(f"text1_with_punc_len:{len(text1)},text2_with_punc_len:{len(text2)}")

    if text1 and text2:
        # 预处理文本一
        text1 = BestMatch.remove_base_txt_lines(text1)
        # 预处理文本二
        text2 = BestMatch.remove_cmp_txt_lines(text2)

        print(f"text1_len:{len(text1)},text2_len:{len(text2)}")

        text1_no_punc, matched_paragraph_no_punc, matched_paragraph, match_rate = (
            BestMatch.find_best_match(text1, text2)
        )

        print("无标点的文本1：")
        print(text1_no_punc)
        print("\n匹配到的无标点的文本2：")
        print(matched_paragraph_no_punc)
        print("\n匹配到的带标点的文本2：")
        print(matched_paragraph)
        print(f"\n匹配率：{match_rate},匹配长度:{len(matched_paragraph)}")

        print(f"\n匹配率：{match_rate:.2%},匹配长度:{len(matched_paragraph)}")
