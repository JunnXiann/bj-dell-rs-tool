import openai
from typing import Optional
import logging
import httpx
import time
import redis
import os
import asyncio
import async_timeout


class QwenManager:
    # 如是研究院
    API_KEY = "sk-d88835f99e7c4606a75e29879b121bf9"  # 替换为实际的Qwen API Key
    # 华鲤
    # API_KEY = "sk-ee48c87f135040e185faa4dc49b70a3e"  # 替换为实际的Qwen API Key

    def __init__(
        self,
        api_key: str = None,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
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
        """使用Qwen模型添加标点"""
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
                    f"开始Qwen API请求，jsz_juanhao:{jsz_juanhao},次数：{attempt},文本长度:{len(text)}"
                )
                # logging.info(f"请求文本：{text}")
                start_time = time.time()

                # 使用异步调用
                # 增加超时上下文管理（修复异步超时不生效问题）
                # async with async_timeout.timeout(120):
                response = await self.client.chat.completions.create(
                    model="qwen-max-latest",
                    messages=[{"role": "user", "content": optimized_prompt}],
                    temperature=0.1,
                    timeout=180.0,
                )

                elapsed = time.time() - start_time
                logging.info(f"Qwen API响应时间: {elapsed:.2f}s,文本长度:{len(text)}")
                # logging.info(f"Qwen API响应内容response: {response}")

                if response.choices[0].message.content:
                    result["data"] = response.choices[0].message.content

                # 更新实际token消耗（假设API返回消耗信息）
                if hasattr(response, "usage"):
                    actual_tokens = response.usage.total_tokens
                    pid = os.getpid()
                    tpm_key = f"qwen:tpm:{pid}"
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

                # if time.time() - all_start_time > 420:  # 总超时7分钟
                #     logging.error(f"请求总超时: {jsz_juanhao},耗时：{time.time() - all_start_time}")
                #     return {'code': 3, 'msg': '总处理时间超限'}

                wait_time = min(1.5**attempt, 30)  # 增加最大等待时间限制
                logging.warning(
                    f"Qwen第{attempt}次重试，等待{wait_time:.1f}秒,jsz_juanhao:{jsz_juanhao}"
                )
                # await asyncio.sleep(wait_time)
                time.sleep(wait_time)

            except Exception as e:
                logging.error(f"Qwen API非重试错误: {str(e)},jsz_juanhao:{jsz_juanhao}")
                result.update(code=1, msg=str(e))
                return result

    # 移除 process_chunk 中的 run_in_executor
    async def process_chunk(self, chunk: str) -> dict:
        """直接调用异步方法"""
        return await self.add_punctuation(chunk)

    def general_chat(self, prompt: str) -> str:
        """Qwen通用对话接口"""
        try:
            response = self.client.chat.completions.create(
                model="qwen-max-latest",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.5,
            )
            return response.choices[0].message.content
        except Exception as e:
            logging.error(f"Qwen聊天接口错误: {str(e)}")
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
        qpm_key = f"qwen:qpm:{pid}"
        tpm_key = f"qwen:tpm:{pid}"
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


# 使用示例
if __name__ == "__main__":

    qwen = QwenManager()

    # 佛经加标点示例
    sutra_text = "如是我闻一时佛在舍卫国祇树给孤独园"
    print("加标点结果:", qwen.add_punctuation(sutra_text))

    # # 普通对话示例
    print("对话响应:", qwen.general_chat("请解释金刚经的核心思想"))
