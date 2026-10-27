from types import SimpleNamespace

import pytest

from audit_agent.common.config import load_settings
from audit_agent.common.llm_client import LLMClient, LLMError, parse_json


class FakeOpenAI:
    """Mimics openai.OpenAI().chat.completions.create."""

    def __init__(self, content: str | None, finish_reason: str = "stop"):
        self.calls: list[dict] = []
        self._content = content
        self._finish = finish_reason
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **request):
        self.calls.append(request)
        message = SimpleNamespace(content=self._content)
        choice = SimpleNamespace(message=message, finish_reason=self._finish)
        usage = SimpleNamespace(model_dump=lambda: {"completion_tokens": 5})
        return SimpleNamespace(choices=[choice], model=request["model"], usage=usage)


@pytest.fixture
def settings(tmp_path):
    return load_settings().llm.model_copy(update={"cache_dir": tmp_path})


MESSAGES = [{"role": "user", "content": "hi"}]


def test_model_comes_from_config_and_second_call_is_cached(settings):
    fake = FakeOpenAI('{"a": 1}')
    client = LLMClient(settings, client=fake)
    first = client.complete(MESSAGES)
    second = client.complete(MESSAGES)
    assert fake.calls[0]["model"] == settings.model
    assert (first.cached, second.cached) == (False, True)
    assert second.text == '{"a": 1}'
    assert len(fake.calls) == 1


def test_truncated_answer_raises_and_is_not_cached(settings):
    fake = FakeOpenAI('{"a":', finish_reason="length")
    client = LLMClient(settings, client=fake)
    with pytest.raises(LLMError, match="truncated"):
        client.complete(MESSAGES)
    assert client.cache.get(client.build_request(MESSAGES)) is None


def test_empty_answer_raises(settings):
    client = LLMClient(settings, client=FakeOpenAI(None))
    with pytest.raises(LLMError, match="empty"):
        client.complete(MESSAGES)


def test_complete_json_uses_json_mode(settings):
    fake = FakeOpenAI('```json\n{"labels": ["litigation"]}\n```')
    assert LLMClient(settings, client=fake).complete_json(MESSAGES) == {"labels": ["litigation"]}
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


def test_parse_json_rejects_garbage():
    with pytest.raises(LLMError):
        parse_json("not json")


def test_provider_rate_limit_maps_to_llm_rate_limit_error(settings):
    from openai import RateLimitError

    from audit_agent.common.llm_client import LLMRateLimitError

    response = SimpleNamespace(request=None, status_code=429, headers={})

    def raise_429(**_: object) -> None:
        raise RateLimitError("free-models-per-day", response=response, body=None)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=raise_429)))
    with pytest.raises(LLMRateLimitError, match="free-models-per-day"):
        LLMClient(settings, client=fake).complete(MESSAGES)
