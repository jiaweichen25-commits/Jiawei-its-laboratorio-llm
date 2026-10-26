"""Modello di chat finto: risposte prestabilite, nessuna chiamata a LM Studio."""

import json
import re

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessageChunk
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult


class ModelloFinto(BaseChatModel):
    risposte: list  # AIMessage o eccezioni, consumate in ordine
    ricevuti: list = []  # messaggi ricevuti a ogni chiamata

    @property
    def _llm_type(self) -> str:
        return "finto"

    def bind_tools(self, tools, **kwargs):
        return self

    def _prossima(self, messages):
        self.ricevuti.append(list(messages))
        risposta = self.risposte.pop(0)
        if isinstance(risposta, BaseException):
            raise risposta
        return risposta

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        return ChatResult(generations=[ChatGeneration(message=self._prossima(messages))])

    def _stream(self, messages, stop=None, run_manager=None, **kwargs):
        risposta = self._prossima(messages)
        for parola in re.findall(r"\S+\s*", risposta.content):
            yield ChatGenerationChunk(message=AIMessageChunk(content=parola))
        if risposta.tool_calls:
            yield ChatGenerationChunk(message=AIMessageChunk(content="", tool_call_chunks=[
                {"name": c["name"], "args": json.dumps(c["args"]), "id": c["id"], "index": i}
                for i, c in enumerate(risposta.tool_calls)
            ]))
