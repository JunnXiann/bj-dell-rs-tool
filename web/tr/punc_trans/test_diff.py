import os
from datetime import datetime
import sys

root_dir = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
print(f"root_dir:{root_dir}")
sys.path.append(root_dir)

from util.punc import transfer_punc_for_stats
import helper as hp

IS_BASE_TEXT = lambda x: x not in "\n[]JS_0123456789"

txt1 = "金光明經者教窮滿字金鼓擊於夢中理極真空寶塔涌於地上三身果備酬昔報之無虧十地因圓顯曩修之具足所以經王之號得稱於斯將知能弘贊人其位難量者也"
txt2 = "《金光明經》者，教窮滿字，金鼓擊於夢中，理極真空，寶塔踊於地上；三身果備，酬昔報之無虧；十地因圓，顯曩修之具足。所以經王之號得稱於斯，將知能弘贊人，其位難量者也。"


def test_diff_txt(txt1, txt2):
    punc_txt, segments = transfer_punc_for_stats(txt1, txt2, IS_BASE_TEXT)
    return punc_txt, segments


if __name__ == "__main__":
    punc_txt, segments = test_diff_txt(txt1, txt2)
    print(f"punc_txt:{punc_txt}\n,segments:{segments}")
