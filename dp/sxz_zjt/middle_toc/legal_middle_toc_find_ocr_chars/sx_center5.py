# -*- coding: utf-8 -*-
"""
@File    : find_bold_edge_fold.py
@Time    : 2025/5/21 22:33
@Author  : zhujiantao
@Version : 1.0
@Desc    : ocr识别对应扣图后，家亮通过字图坐标提取疑似版心列扣图，这里通过版心列文字特征及字图位置提取正确版心列
特征：1.版心列字数大于3小于14，版心列第一个字符坐标纵坐标大于扣图高度的0.23倍
2.第一个字符必须为千字文
3.第二个字符符合大写数字
4.版心列包含‘卷’字
注意：生成的has_middle_toc_fold_id_list_5.json 不包含 has_middle_toc_fold_id_list_4.json中的扣id
"""
import sys
import json
from os import path

sys.path.append(path.dirname(path.dirname(path.dirname(path.dirname(path.dirname(path.abspath(__file__)))))))
import helper as hp

thousand_char_str = "天地玄黃宇宙洪荒日月盈昃辰宿列張寒來暑往秋收冬藏閏餘成歲律呂調陽雲騰致雨露結為霜金生麗水玉出昆岡劍號巨闕珠稱夜光果珍李柰菜重芥姜海咸河淡鱗潛羽翔龍師火帝鳥官人皇始製文字乃服衣裳推位讓國有虞陶唐吊民伐罪周發殷湯坐朝問道垂拱平章愛育黎首臣伏戎羌遐邇一體率賓歸王鳴鳳在竹白駒食場化被草木賴及萬方蓋此身發四大五常恭惟鞠養豈敢毀傷女慕貞潔男效才良知過必改得能莫忘罔談彼短靡恃己長信使可複器欲難量墨悲絲染詩贊羔羊景行維賢克念作聖德建名立形端表正空谷傳聲虛堂習聽禍因惡積福緣善慶尺璧非寶寸陰是競資父事君曰嚴與敬孝當竭力忠則盡命臨深履薄夙興溫凊似蘭斯馨如松之盛川流不息淵澄取映容止若思言辭安定篤初誠美慎終宜令榮業所基籍甚無竟學優登仕攝職從政存以甘棠去而益詠樂殊貴賤禮別尊卑上和下睦夫唱婦隨外受傅訓入奉母儀諸姑伯叔猶子比兒孔懷兄弟同氣連枝交友投分切磨箴規仁慈隱惻造次弗離節義廉退顛沛匪虧性靜情逸心動神疲守真誌滿逐物意移堅持雅操好爵自縻都邑華夏東西二京背邙面洛浮渭據涇宮殿盤鬱樓觀飛驚圖寫禽獸畫彩仙靈丙舍傍啟甲帳對楹肆筵設席鼓瑟吹笙升階納陛弁轉疑星右通廣內左達承明既集墳典亦聚群英杜稿鐘隸漆書壁經府羅將相路俠槐卿戶封八縣家給千兵高冠陪輦驅轂振纓世祿侈富車駕肥輕策功茂實勒碑刻銘磻溪伊尹佐時阿衡奄宅曲阜微旦孰營桓公匡合濟弱扶傾綺回漢惠說感武丁俊逸密勿多士寔寧晉楚更霸趙魏困橫假途滅虢踐土會盟何遵約法韓弊煩刑起翦頗牧用軍最精宣威沙漠馳譽丹青九州禹跡百郡秦並岳宗泰岱禪主雲亭雁門紫塞雞田赤城昆池碣石巨野洞庭曠遠綿邈岩岫杳冥治本於農務資稼穡俶載南畝我藝黍稷稅熟貢新勸賞黜陟孟軻敦素史魚秉直庶幾中庸勞謙謹敕聆音察理鑒貌辨色貽厥嘉猷勉其祗植省躬譏誡寵增抗極殆辱近恥林皋幸即兩疏見機解組誰逼索居閒處沉默寂寥求古尋論散慮逍遙欣奏累遣戚謝歡招渠荷的歷園莽抽條枇杷晚翠梧桐蚤凋陳根委翳落葉飄搖游鵾獨運凌摩絳霄耽讀玩市寓目囊箱易輶攸畏屬耳垣牆具膳餐飯適口充腸飽飫烹宰饑厭糟糠親戚故舊老少異糧妾御績紡侍巾帷房紈扇圓絜銀燭煒煌晝眠夕寐藍筍象床弦歌酒宴接杯舉觴矯手頓足悅豫且康嫡後嗣續祭祀烝嘗稽顙再拜悚懼恐惶箋牒簡要顧答審詳骸垢想浴執熱願涼驢騾犢特駭躍超驤誅斬賊盜捕獲叛亡布射僚丸嵇琴阮嘯恬筆倫紙鈞巧任釣釋紛利俗並皆佳妙毛施淑姿工顰妍笑年矢每催曦暉朗曜璇璣懸斡晦魄環照指薪修祜永綏吉劭矩步引領俯仰廊廟束帶矜莊徘徊瞻眺孤陋寡聞愚蒙等誚謂語助者焉哉乎也"

number_char_str = "一二三四五六七八九十百"


def get_center_page():
    """
    得到包含版心列的扣id列表
    :return:
    """
    # 得到数据库链接
    db_work = hp.get_db('tw-work')
    # 443039代表思溪藏 is_center表示版心列
    cond2 = {'flag': 443039,'columns': {'$elemMatch': {'is_center': True}}}
    # 得到所有页编码
    names = db_work.page.distinct('name', cond2)
    # 将页编码从小到大排序
    sorted_lst = sorted(names, key=lambda x: [int(y) for y in x.split('_') if
                                              y.isdigit()])
    # 将页编码列表分割每个元素为100个页面列表的列表
    split_lst = [sorted_lst[i:i + 100] for i in range(0, len(sorted_lst), 100)]

    # 带有版心列的扣id列表
    has_middle_toc_fold_id_list = []

    with open("has_middle_toc_fold_id_list_1.json", "r") as f:
        has_middle_toc_fold_id_list.extend(json.loads(f.read()))

    with open("has_middle_toc_fold_id_list_3.json", "r") as f:
        has_middle_toc_fold_id_list.extend(json.loads(f.read()))

    with open("has_middle_toc_fold_id_list_4.json", "r") as f:
        has_middle_toc_fold_id_list.extend(json.loads(f.read()))

    new_has_middle_toc_fold_id_list = []

    for i, lst in enumerate(split_lst):
        # 根据页编码找到页数据列表
        pages = list(db_work.page.find({'name':{'$in':lst}}))
        for page in pages:
            # 找到版心列
            center_columns = [c['column_id'] for c in page.get('columns', []) if
                              not c.get('deleted') and c.get('is_center')]
            # 定义列与字数据列表对应的字典 {column_id: [char1, char2]...}
            col2chars = {}
            for char in page.get('chars', []):
                if char.get('deleted'):
                    continue
                # 从字id中获取列id 字id格式为b1c2c3 b代表栏block 第一个c代表列column 第二个c代表字符char
                column_id = char['char_id'].rsplit('c', 1)[0]
                if column_id not in col2chars.keys():
                    col2chars[column_id] = [char]
                else:
                    col2chars[column_id].append(char)

            # 字符纵坐标阈值
            first_char_y_threshold = page.get('height') *0.23

            for column_id in center_columns:
                chars = col2chars.get(column_id,[])
                if chars:
                    # 得到版心列的内容
                    middle_txt_str = "".join([tmp.get("ocr_txt", "") for tmp in chars])
                    # 得到字符下方边缘纵坐标
                    first_char_y = chars[0]['y'] + chars[0]['h']
                    # 字符数量大于4 且 小于13 且 字符纵坐标小于阈值则认为是有效版心列 之前是3到11个
                    if len(chars) > 1:
                        fold_id = page['name']
                        if "卷" in middle_txt_str:
                            # print(f"fold_id={fold_id} 千字文:{middle_txt_str}")
                            if fold_id not in has_middle_toc_fold_id_list:
                                print(f"fold_id={fold_id} 千字文:{middle_txt_str}")
                                # 追加扣id
                                new_has_middle_toc_fold_id_list.append(fold_id)

    print(f"合格版心列扣数量={len(new_has_middle_toc_fold_id_list)}")
    with open("has_middle_toc_fold_id_list_5.json", "w") as f:
        f.write(json.dumps(new_has_middle_toc_fold_id_list))


if __name__ == '__main__':
    get_center_page()
