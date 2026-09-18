try:
    from cdifflib import CSequenceMatcher
except ImportError:  # Windows、Mac arm64e 上跳过安装cdifflib
    try:
        from difflib import SequenceMatcher as CSequenceMatcher
    except ImportError:
        class SequenceMatcher:
            def __init__(self, a, b, autojunk=True):
                pass

            def get_opcodes(self):
                return []
