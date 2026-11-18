"""为各任务生成结构化结果，向量嵌入使用独立客户端。
Generate structured results per task and use a separate client for embeddings.
"""
import json
import os
from types import SimpleNamespace

from jsonschema import validate


def configuration(task, api_key=None):
    prefix = 'LLM_' + task.upper()
    provider = os.getenv(prefix + '_PROVIDER', 'nvidia')
    if provider not in ('openai', 'nvidia'):
        raise ValueError('unsupported LLM provider')
    key = api_key if api_key is not None else os.getenv('NVIDIA_API_KEY' if provider == 'nvidia' else 'OPENAI_API_KEY', '')
    defaults = {'ultra': 'nvidia/nemotron-3-ultra-550b-a55b',
                'review': 'nvidia/nemotron-3-ultra-550b-a55b',
                'sentiment': 'nvidia/nemotron-3.5-lightning-30b-a3b',
                'vision': 'nvidia/nemotron-3.5-super-vl-120b-a12b'}
    default = defaults.get(task, 'deepseek-ai/deepseek-v4.1-flash') if provider == 'nvidia' else os.getenv('OPENAI_MODEL', 'gpt-5-mini')
    return dict(provider=provider, key=key.strip(), model=os.getenv(prefix + '_MODEL', default), task=task)


class StructuredClient:
    def __init__(self, config):
        self.config = {'task': 'advice', **config}
        self.responses = self

    def create(self, *, model=None, input, text, max_output_tokens):
        from ai_runtime import reserve, finish, retry_seconds
        cfg = self.config
        identity = reserve(cfg['task'], cfg['model']) if cfg['provider'] == 'nvidia' else None
        try:
            result = self._create(model=model, input=input, text=text, max_output_tokens=max_output_tokens)
        except Exception as error:
            if identity:
                finish(identity, type(error).__name__, retry_after=retry_seconds(error) if getattr(error, 'status_code', None) == 429 else None)
            raise
        if identity:
            finish(identity, 'completed', int(getattr(result.usage, 'total_tokens', 0) or 0))
        return result

    def _create(self, *, model=None, input, text, max_output_tokens):
        from openai import OpenAI
        cfg = self.config
        client = OpenAI(api_key=cfg['key'], timeout=120 if cfg['task'] in ('ultra', 'review') else 45, max_retries=0,
                        base_url='https://integrate.api.nvidia.com/v1' if cfg['provider'] == 'nvidia' else None)
        spec = text['format']
        if cfg['provider'] == 'openai':
            response = client.responses.create(model=cfg['model'], input=input, text=text, max_output_tokens=max_output_tokens)
            if getattr(response, 'status', 'completed') != 'completed' or not response.output_text:
                raise ValueError('incomplete structured response')
            output, usage = response.output_text, response.usage
        else:
            messages = [{'role': row['role'], 'content': row['content'] if isinstance(row['content'], str) else
                         [({'type': 'text', 'text': part['text']} if part['type'] == 'input_text' else part) for part in row['content']]} for row in input]
            options = {}
            if (cfg['model'] == 'deepseek-ai/deepseek-v4.1-flash'
                    and cfg['task'] in ('advice', 'advice_background', 'review')):
                # 该端点可能在正常结束时只返回推理内容。禁用推理模式以获取最终 JSON。
                # This endpoint can finish with reasoning content alone. Disable thinking to get the final JSON.
                options['extra_body'] = {'chat_template_kwargs': {'thinking': False}}
            response = client.chat.completions.create(model=cfg['model'], messages=messages,
                response_format={'type': 'json_schema', 'json_schema': {k: v for k, v in spec.items() if k != 'type'}},
                max_tokens=max_output_tokens, **options)
            choice = response.choices[0]
            if choice.finish_reason != 'stop' or not choice.message.content:
                raise ValueError('incomplete structured response')
            output, usage = choice.message.content, response.usage
        def invalid_constant(value):
            raise ValueError('nonfinite JSON number')
        validate(json.loads(output, parse_constant=invalid_constant), spec['schema'])
        return SimpleNamespace(output_text=output, usage=usage, model=cfg['model'])


def structured_client(task, api_key=None):
    cfg = configuration(task, api_key)
    return StructuredClient(cfg) if cfg['key'] else None
