import openai
from typing import Optional
import logging
import httpx  # 新增导入


class DeepseekManager:
    # 如是研究院
    API_KEY = "sk-8e03333a781e4e6cbf9c5a5cbe59d0d7"

    def __init__(
        self, api_key: str = None, base_url: str = "https://api.deepseek.com/v1"
    ):
        self._init_session()
        self.client = openai.OpenAI(
            base_url=base_url,
            api_key=api_key if api_key else self.API_KEY,
            http_client=self._session,  # 使用包装后的session
            timeout=httpx.Timeout(30.0),  # 新增超时设置
        )

    def _init_session(self):
        """初始化带重试机制的HTTP会话"""
        transport = httpx.HTTPTransport(retries=3)
        self._session = httpx.Client(transport=transport, timeout=30.0)  # 设置默认超时

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._session.close()

    def add_punctuation(self, text: str, jsz_juanhao="") -> dict:
        """优化后的标点添加方法"""
        optimized_prompt = f"""请为以下佛经文本添加正确标点符号，需满足：
1. 严格保持原文内容和语序
2. 标点需符合文言文特征和佛教经典格式
3. 若文本过短你觉得无需打标或者已有标点恰当，则保持原样
4. 使用中文标点
5. 请直接返回添加标点后的文本，不要包含任何解释或注释

待处理文本：{text}"""

        result = {"code": 0, "msg": "", "data": []}

        try:
            response = self.client.chat.completions.create(
                model="deepseek-reasoner",
                messages=[{"role": "user", "content": optimized_prompt}],
                temperature=0.1,
            )
            logging.info(f"add_punctuation,response:{response}")

            # 记录成功日志
            if response.choices[0].message.content:
                logging.info(
                    f"Processed text: {text[:50]}..."
                )  # 打印前50字符避免日志过长
                logging.info(f"Used tokens: {response.usage.total_tokens}")

            result[data] = response.choices[0].message.content

        except Exception as e:
            logging.info(
                f"deepseek_api_error,请求错误 | {e.__class__.__name__}: {str(e)}"
            )
            result["code"] = 1
            result["msg"] = str(e)
        return result

    def check_balance(self) -> dict:
        """查询账户余额"""
        return self._call_account_api("/balance")

    def get_token_usage(self, date: str) -> dict:
        """查询指定日期的token使用量"""
        return self._call_account_api(f"/usage?date={date}")

    def general_chat(self, prompt: str) -> str:
        """通用对话接口"""
        response = self.client.chat.completions.create(
            model="deepseek-chat",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
        )
        return response.choices[0].message.content

    def _call_account_api(self, endpoint: str) -> dict:
        """调用账户相关API（示例实现）"""
        # 实际实现需替换为真实的API调用
        return {"status": "success", "data": "示例响应"}


# 使用示例
if __name__ == "__main__":

    deepseek = DeepseekManager()

    # 佛经加标点示例
    sutra_text = "如是我闻一时佛在舍卫国祇树给孤独园"
    print("加标点结果:", deepseek.add_punctuation(sutra_text))

    # 账户查询示例
    # print("账户余额:", deepseek.check_balance())
    # print("今日用量:", deepseek.get_token_usage("2024-03-15"))

    # # 普通对话示例
    print("对话响应:", deepseek.general_chat("请解释金刚经的核心思想"))
