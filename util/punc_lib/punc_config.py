class GlobalDBVars:
    _instance = None
    
    def __init__(self):
        self.rushi_dev_client = None
        self.check_online_read_client = None
        self.test_client = None
        self.jsz_collection = None
        self.jsz_source_mapping_collection = None
        self.big_model_punc_details_collection = None
        self.reel_bd_collection = None
        self.sutra_sources_collection = None
        self.test_pubnote_collection = None
        self.test_sutra_sources_collection = None
        self.sutra_sources_collection = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

global_db_vars = GlobalDBVars.instance()