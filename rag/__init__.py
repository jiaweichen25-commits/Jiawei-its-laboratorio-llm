"""Lezione 7: pipeline RAG sul ricettario di Artusi (ingestion e ricerca semantica).

Due fasi (slide 5):
  1. ingestion (`python -m rag.ingestion`): testo → ricette → chunk → embedding → Qdrant;
  2. ricerca (`python -m rag.ricerca "domanda"`): domanda → embedding → i k chunk più vicini, con la fonte.

In questa lezione il modello generativo non c'entra: si costruisce e si misura solo il recupero.
Nella lezione 8 la ricerca diventerà uno strumento dell'agente.
"""
