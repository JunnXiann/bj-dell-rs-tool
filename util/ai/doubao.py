import openai
from typing import Optional
import logging
import httpx
import time
import redis
import os
import asyncio
import async_timeout


class DoubaoManager:
    # 如是研究院
    API_KEY = "edd9b46f-3e3c-4b40-94a7-d710d4c95735"
    # 华鲤
    # API_KEY = "edd9b46f-3e3c-4b40-94a7-d710d4c95735"

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://ark.cn-beijing.volces.com/api/v3",
    ):

        # 新增Redis连接配置
        self.redis_cli = redis.Redis(host="localhost", port=6379, db=0)
        try:
            self.redis_cli.ping()
        except redis.ConnectionError:
            logging.error("Redis连接失败，请检查服务是否运行")
            raise

        self._async_init_session()

        self.client = openai.AsyncOpenAI(
            base_url=base_url,
            api_key=api_key if api_key else self.API_KEY,
            http_client=self._session,
            timeout=httpx.Timeout(150.0),
        )

        # 新增限流队列
        self.request_times = []  # 记录请求时间戳
        self.token_usages = []  # 记录token消耗量
        self.max_qpm = 500  # 最大请求数/分钟，官方实际1200
        self.max_tpm = 900000  # 最大token/分钟，官方实际1000000

    def _async_init_session(self):
        """初始化异步HTTP会话"""
        from urllib3.util import Retry

        retry_strategy = Retry(
            total=1,
            backoff_factor=2,
            status_forcelist=[500, 502, 503, 504],  # 429本身就是太频繁了不要重试
            allowed_methods=["POST"],
            respect_retry_after_header=True,  # 遵守服务端返回的retry-after时间
        )

        # 使用异步客户端
        self._session = httpx.AsyncClient(
            timeout=180.0,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            transport=httpx.AsyncHTTPTransport(
                retries=retry_strategy,
                verify=False,
                limits=httpx.Limits(  # 添加连接池限制
                    max_connections=10, max_keepalive_connections=5  # 降低最大连接数
                ),
            ),
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._session.aclose()

    async def add_punctuation(self, text: str, jsz_juanhao="") -> dict:
        """使用模型添加标点"""
        await self._rate_limit_check(text)  # 新增限流检查

        optimized_prompt = f"""请为以下佛经文本添加正确标点符号，需满足：
1. 严格保持原文内容和语序，请不要修改原文内容
2. 标点需符合文言文特征和佛教经典格式
3. 若文本过短你觉得无需打标或者已有标点恰当，则保持原样
4. 使用中文标点
5. 请直接返回添加标点后的文本，不要包含任何解释或注释

待处理文本：{text}"""

        result = {"code": 0, "msg": "", "data": ""}
        all_start_time = time.time()
        max_retries = 2

        for attempt in range(1, max_retries + 1):
            try:
                logging.info(
                    f"开始Doubao API请求，jsz_juanhao:{jsz_juanhao},次数：{attempt},文本长度:{len(text)}"
                )
                # logging.info(f"请求文本：{text}")
                start_time = time.time()

                # 使用异步调用
                # 增加超时上下文管理（修复异步超时不生效问题）
                # async with async_timeout.timeout(120):
                response = await self.client.chat.completions.create(
                    model="doubao-1-5-pro-32k-250115",
                    messages=[{"role": "user", "content": optimized_prompt}],
                    temperature=0.1,
                    timeout=180.0,
                )

                elapsed = time.time() - start_time
                logging.info(f"Doubao API响应时间: {elapsed:.2f}s,文本长度:{len(text)}")
                # logging.info(f"Doubao API响应内容response: {response}")

                if response.choices[0].message.content:
                    # 违禁词
                    if (
                        "你好，这个问题我无法回答，很遗憾不能帮助你"
                        in response.choices[0].message.content
                    ):
                        result["code"] = 3
                        result["data"] = "你好，这个问题我无法回答，很遗憾不能帮助你。"
                    else:
                        result["data"] = response.choices[0].message.content

                # 更新实际token消耗（假设API返回消耗信息）
                if hasattr(response, "usage"):
                    actual_tokens = response.usage.total_tokens
                    pid = os.getpid()
                    tpm_key = f"doubao:tpm:{pid}"
                    tpm_data_key = f"{tpm_key}_data"

                    # 生成唯一ID（与限流检查一致）
                    unique_id = f"{start_time}_{hash(text)}"

                    # 使用管道原子更新
                    pipe = self.redis_cli.pipeline()
                    pipe.zadd(tpm_key, {unique_id.encode("utf-8"): start_time})
                    pipe.hset(
                        tpm_data_key, unique_id.encode("utf-8"), str(actual_tokens)
                    )
                    pipe.execute()

                return result

            except (
                httpx.TimeoutException,
                httpx.NetworkError,
                openai.APITimeoutError,
            ) as e:  # 新增OpenAI超时异常
                if attempt >= max_retries:  # 最终尝试失败
                    logging.error(
                        f"最终重试失败: {str(e)}，jsz_juanhao:{jsz_juanhao},文本长度: {len(text)}，文本: {text}"
                    )
                    result.update(code=2, msg="API请求超时")
                    return result

                wait_time = min(1.5**attempt, 30)  # 增加最大等待时间限制
                logging.warning(
                    f"Doubao第{attempt}次重试，等待{wait_time:.1f}秒,jsz_juanhao:{jsz_juanhao}"
                )
                # await asyncio.sleep(wait_time)
                time.sleep(wait_time)

            except Exception as e:
                logging.error(
                    f"Doubao API非重试错误: {str(e)},jsz_juanhao:{jsz_juanhao}"
                )
                result.update(code=1, msg=str(e))
                return result

    # 移除 process_chunk 中的 run_in_executor
    async def process_chunk(self, chunk: str) -> dict:
        """直接调用异步方法"""
        return await self.add_punctuation(chunk)

    async def general_chat(self, prompt: str) -> str:
        """Doubao通用对话接口"""
        try:
            response = await self.client.chat.completions.create(
                model="doubao-1-5-pro-32k-250115",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Doubao聊天接口错误: {str(e)}")
            return "服务暂不可用"

    # 文本切块
    def split_text_by_length(self, text: str, max_length: int = 3000) -> list:
        """
        将长文本按最大长度分割，尽量在自然断句处分隔
        :param text: 待分割文本
        :param max_length: 单块最大长度
        :return: 分割后的文本块列表
        """
        if len(text) <= max_length:
            return [text]

        chunks = []
        current_chunk = ""

        # 优先在段落分隔处分割
        paragraphs = text.split("\n")
        for para in paragraphs:
            if len(current_chunk) + len(para) < max_length:
                current_chunk += para + "\n"
            else:
                # 段落太长时按句子分割
                sentences = []
                temp_sentence = ""
                for char in para:
                    temp_sentence += char
                    if char in ("。", "！", "？", "；"):
                        sentences.append(temp_sentence)
                        temp_sentence = ""
                if temp_sentence:
                    sentences.append(temp_sentence)

                # 按句子重组
                for sentence in sentences:
                    if len(current_chunk) + len(sentence) < max_length:
                        current_chunk += sentence
                    else:
                        if current_chunk:
                            chunks.append(current_chunk.strip())
                        current_chunk = sentence

        if current_chunk:
            chunks.append(current_chunk.strip())

        return chunks

    async def add_punctuation_with_chunks(self, text: str, jsz_juanhao="") -> dict:
        """
        支持长文本的标点添加函数
        :param text: 待处理文本
        :return: 处理结果字典 {'code': 0, 'msg': '', 'data': '标点结果'}
        """
        chunks = self.split_text_by_length(text)
        results = []

        for chunk in chunks:
            result = await self.process_chunk(chunk)
            if result["code"] != 0:
                return result  # 任意一块失败则整体失败
            results.append(result["data"])

        return {"code": 0, "msg": "", "data": "".join(results)}

    async def _rate_limit_check(self, text: str):
        """使用Redis实现跨进程限流（完整修正版）"""
        now = time.time()
        current_tokens = len(text) * 2
        pid = os.getpid()

        # 统一键名定义
        qpm_key = f"doubao:qpm:{pid}"
        tpm_key = f"doubao:tpm:{pid}"
        tpm_data_key = f"{tpm_key}_data"

        # 生成唯一请求ID（时间戳+哈希值）
        unique_id = f"{now}_{hash(text)}"

        # 使用管道原子操作
        pipe = self.redis_cli.pipeline()

        # 清理过期记录（精确到当前进程）
        pipe.zremrangebyscore(qpm_key, "-inf", now - 60)
        pipe.zremrangebyscore(tpm_key, "-inf", now - 60)

        # 自动清理hash中的过期数据（修复字节编码问题）
        expired_ids = [
            mid.decode("utf-8")
            for mid in self.redis_cli.hkeys(tpm_data_key)
            if float(mid.decode("utf-8").split("_")[0]) < now - 60
        ]
        if expired_ids:
            pipe.hdel(tpm_data_key, *[id.encode("utf-8") for id in expired_ids])

        # 添加预记录（先假设使用预估token数）
        pipe.zadd(qpm_key, {unique_id.encode("utf-8"): now})
        pipe.zadd(tpm_key, {unique_id.encode("utf-8"): now})
        pipe.hset(tpm_data_key, unique_id.encode("utf-8"), str(current_tokens))
        pipe.execute()

        # 获取实际有效TPM（精确时间窗口）
        valid_ids = [
            mid.decode("utf-8")
            for mid in self.redis_cli.zrangebyscore(tpm_key, now - 60, now)
        ]
        current_tpm = sum(
            int(self.redis_cli.hget(tpm_data_key, mid.encode("utf-8")) or 0)
            for mid in valid_ids
        )

        # QPM限流检查
        current_qpm = len(valid_ids)
        logging.info(f"current_qpm: {current_qpm}, max_qpm: {self.max_qpm}")
        if current_qpm >= self.max_qpm:
            oldest = self.redis_cli.zrange(qpm_key, 0, 0, withscores=True)[0][1]
            wait_time = max(60 - (now - oldest), 0.1)
            logging.warning(
                f"QPM超限({current_qpm}/{self.max_qpm})，等待{wait_time:.1f}秒"
            )
            await asyncio.sleep(wait_time)

        # TPM限流检查
        logging.info(
            f"current_tpm: {current_tpm}, current_tokens:{current_tokens},all_token:{(current_tpm + current_tokens)},max_tpm: {self.max_tpm}"
        )
        if (current_tpm + current_tokens) > self.max_tpm:
            oldest = self.redis_cli.zrange(tpm_key, 0, 0, withscores=True)[0][1]
            wait_time = max(60 - (now - oldest), 0.1)
            logging.warning(
                f"TPM超限({current_tpm + current_tokens}/{self.max_tpm})，等待{wait_time:.1f}秒"
            )
            await asyncio.sleep(wait_time)


async def main():
    doubao = DoubaoManager()

    # 佛经加标点示例
    sutra_text = """佛住王舍城爾時世尊制戒不聽漏心男子邊取衣
缽飲食疾病湯藥時樹提比丘尼不取長者施衣時
偷蘭難陀比丘尼語樹提言何不取此男子施男子
漏心不漏心何豫人事但使汝無漏心取巳隨因緣
用諸比丘尼諫是比丘尼莫作是語男子漏心不漏
心何豫人事但使汝無漏心可取此施隨因緣用如
是二諫三諫不止諸比丘尼以是事語大愛道大愛
道即以是事往白世尊佛言呼比丘尼來來巳佛問
汝實爾不答言實爾佛言此是惡事汝云何勸彼取
漏心人施此非法非律不如佛教不可以是長養善
法佛語大愛道依止王舍城住比丘尼皆悉令集乃
至巳聞者當重聞若比丘尼語比丘尼作是語可取
此男子施漏心不漏心何豫汝事但汝莫漏心可取
施巳隨因緣用諸比丘巳應諫是比丘尼莫作是語
應取是施男子漏心不漏心何豫人事但使汝無漏
心可取施巳隨因緣用如是應第二第三諫捨是事
好若不捨者是法初罪僧伽婆尸沙作是語比丘尼"""

    sutra_text = """
 切忌以手掩面何故明眼底覰著將謂雪竇 門下教你學老婆禪 福嚴容云老姥不欲見佛天然氣槩東西總皆是 佛氣槩天然於此見得老姥即佛佛即老姥不然 則有寒暑兮促君壽有鬼神兮妒君福 黃檗琦云不欲見佛風平浪靜總皆是佛水漲船 高瞿曇節文則且置且道老姥風騷在什麼處若 不同床睡焉知被底穿 清化嶾云雪竇失卻一隻眼殊不知者老婆猶帶 脂粉氣在見個黃面老子即便迴避若見山河大 地草木叢林又向什麼處迴避還有爲雪竇出氣 者麼出來試道看 崇先奇云城東老姥其知可及其愚不可及既知 無處迴避何故以手掩面婦女態度一時露出即 [JS_213_1186] 今還有不欲見佛者麼 漏澤杲云有底道幸自可憐生苦苦相逼他作甚 麼有底道人人自巳是佛更向何處迴避似則似 是則未是山僧黨理不黨親敢道釋迦老子被城 東覰破何也掀翻海嶽求知巳撥轉乾坤見太平 安國聰云婆子眼空四海旁若無人宛有丈夫氣 槩是則固是將手掩面不欲見佛殊不知此處無 銀三十兩 文峰玉云婆子忒殺逞俊殊不知也是日下逃影 廣額屠兒於涅槃會上放下屠刀便曰我是賢劫千 佛一數 東山覺云今時叢林將爲廣額是過去一佛權現 屠兒且喜没交涉又謂廣額是殺人不眨眼底漢 颺下屠刀立便成佛且喜没交涉又謂廣額放下 屠刀曰我是千佛一數者一佛多少分明且喜没 交涉要識廣額麼夾路桃花風雨後馬蹄何處避 殘紅 城山洽云者屠兒都謂有大人之作檢點將來也 是瞎驢趁隊何故不見道丈夫自有冲天志豈向 他人行處行 [JS_213_1187] 波羅提尊者示異見王曰在胎爲身處世爲人在眼 曰見在耳曰聞在鼻辨香在舌談論在手執捉在足 運奔遍現俱該法界收拾在一微塵識者知是佛性 不識喚作精魂王聞感悟 徑山杲云即今問諸人畢竟那個是佛性那個是 精魂 天寧琦云書頭教娘勤作息書尾教娘莫瞌睡還 識娘面嘴麼玉容寂寞淚欄杆梨花一枝春帶雨 松隱然云諸方盡道異見王聞法開悟殊不知波 羅提尊者被王一拶直得技窮力盡進退無門妙 喜盡平生力也救他不得龍峰今日路見不平出 一隻手去也乃喝一喝云適來異見王波羅提妙 喜盡向者裡掃蹤滅跡了也更說甚麼佛性精魂 作用見聞盡是陽燄空花不勞把捉且歸家穩坐 一句作麼生道太平天子朝元日五色雲車駕六 龍 瀛山誾云當時喚作佛性尊者面皮巳厚三尺更 說八處作用教壞人家男女不少雖然如是比他 一等弄精魂手腳猶較些子 能仁鑑云便與麼會喚作依通巳眼未開無自由 [JS_213_1188] 分直須竿頭進步絕後再甦始得一爲無量無量 爲一小中現大大中現小雖然還識祖師麼爲憐 三歲子不惜兩莖眉 洞山瑩拈拂子拂一拂云者個是佛性將什麼喚 作精魂又拂一拂云者個是精魂將什麼喚作佛 性復連拂兩拂云痴人面前不得說夢便擿下拂 子 大覺昇云大小尊者只識得精魂佛性未夢見在 今日有問佛性在什麼處向道趙錢孫李周吳鄭 王 龍華體云且道精魂與佛性相去多少點石化爲 金玉易勸人除卻是非難 勝思惟梵天謂不退轉天子曰天子我常於此佛國 土不曾見汝天子曰梵天我亦不曾於此國土不曾 見我 天童悟云者兩個漢各自分疆立界各各不相見 各各自稱尊殊不顧旁觀者醜 大愚鵬云不曾見汝不曾見我一對無孔鐵錘難 爲勘破我當時若見各與他二十拄杖 障蔽魔王領諸眷屬一千年隨金剛齊菩薩覓起處 [JS_213_1189] 不得忽一日得見乃問曰汝依何而住我一千年覓 汝起處不得齊曰我不依有住而住不依無住而住 如是而住 法眼益云障蔽魔王不見金剛齊即且從只如金 剛齊還見障蔽魔王麼 徑山杲云既覓起處不得一千年隨從的是什麼 我不依有住而住不依無住而住如是而住互相 熱瞞法眼道障蔽魔王不見金剛齊即且從只如 金剛齊還見障蔽魔王麼恁麼批判也是看孔著 楔只今莫有知妙喜起處底麼乃喝一喝云寐語 作麼 天寧琦云金剛齊道我不依有住而住不依無住 而住一時被障蔽魔王捉敗了也雖然也須扶起 金剛齊始得 雲門信云金剛齊太殺漏逗既不依有無而住怎 麼又被魔王覰見 資福侶徵云一千年覓起處不得爲甚麼忽一日 得見莫是金剛齊滲漏麼莫是魔王眼花麼咄 須菩提尊者因說法次帝釋雨花乃問此花從天得 耶曰弗也從人得耶曰弗也畢竟從何而得帝釋乃 [JS_213_1190] 舉手尊者曰如是如是 雲門偃云帝釋舉手處與你四大五藴釋迦老子 是同是别 天寧琦云澤廣藏山理能伏豹放過須菩提尊者 尋常將什麼說法也好與一拶 天寧慧云帝釋舉手尊者如是彼此都來熱瞞到 天寧者裡各與他二十拄杖 雲門澄云帝釋舉手尊者如是未免互相熱瞞祖 師門下無如是事我若作尊者待伊舉手便與熱 喝要使帝釋天别有生涯 白巖符云大小尊者乞兒見小利我則不然當時 見帝釋舉手便一直向他道不是不是 須菩提巖中宴坐諸天雨花讚歎尊者問空中雨花 讚歎復是何人云何讚歎曰我是梵天敬重尊者善 說般若尊者曰我於般若未曾說一字汝云何讚歎 曰如是尊者無說我乃無聞無說無聞是真說般若 雪竇顯云避喧求靜處世未有其方他在巖中宴 座也被者一隊漢塗汙更有者老漢把不住問空 中雨花讚歎復是何人早見敗闕了也我重尊者 善說般若惡水驀頭潑又云我於般若未嘗說一 [JS_213_1191] 字草裡走尊者無說我乃無聞識甚好惡總似者 般底漢何處有今日復召云大眾雪竇幸是無事 你來者裡覓個甚麼碗以拄杖一時趁散 磬山修舉雪竇語畢云明覺老漢似個築漏洞底 一般空生梵天底不妨築著自家底漏洞還曾築 著也無 薦福如云大小空生不善宴座惹得一隊漢撒沙 撒土當面塗汙一上如來弟子解空何在當時但 兀坐不釆梵天縱有惡水管教無處澆潑 龍華宗云須菩提老老大大開眼著賊也不知 賓頭盧尊者因阿育王内宮齋三萬大阿羅漢躳自 行香
"""
    punc_res = await doubao.add_punctuation(sutra_text)
    print("加标点结果:", punc_res)

    # # 普通对话示例
    # print("对话响应:", await doubao.general_chat("请解释金刚经的核心思想"))


# 使用示例
if __name__ == "__main__":
    import asyncio

    asyncio.run(main())  # 使用 asyncio 运行异步主函数
