"""La collezione Qdrant: creazione, controlli, salvataggio ripetibile e ricerca.

Un punto della collezione (slide 16) = ID + vettore + payload (testo e metadati del chunk).
Il database non è uno strumento dell'agente: lo interrogano solo l'ingestion e la ricerca.
"""

from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from rag.chunking import Chunk, id_punto

MASSIMO_K = 20   # limite imposto dal codice (slide 25): un k grande porta testo irrilevante
_LOTTO_UPSERT = 128
FONTE = "Artusi, La scienza in cucina e l'arte di mangiar bene (1891)"


class ErroreArchivio(Exception):
    """Collezione assente, incompatibile con la configurazione o filtro non valido."""


@dataclass(frozen=True)
class Risultato:
    classifica: int     # 1 = il più simile
    score: float        # similarità del coseno: vicinanza, non probabilità (slide 9)
    numero: int
    titolo: str
    capitolo: str
    posizione: int
    chunk_totali: int
    testo: str


@dataclass(frozen=True)
class EsitoSalvataggio:
    scritti: int
    rimossi: int


def payload(chunk: Chunk) -> dict:
    """Testo e metadati salvati con il vettore: servono a citare, filtrare e ritrovare il chunk."""
    return {
        "documento_id": chunk.documento_id,
        "numero": chunk.numero,
        "titolo": chunk.titolo,
        "capitolo": chunk.capitolo,
        "posizione": chunk.posizione,
        "chunk_totali": chunk.chunk_totali,
        "testo": chunk.testo,
        "fonte": f"{FONTE}, ricetta {chunk.numero}",
    }


class Archivio:
    def __init__(self, client: QdrantClient, collezione: str):
        self.client = client
        self.collezione = collezione

    # ------------------------------------------------------------------ collezione e controlli

    def _metadati_attesi(self, modello: str, dimensione: int, prefissi: bool) -> dict:
        return {"modello_embedding": modello, "dimensione": dimensione, "prefissi": prefissi}

    def _controlla(self, modello: str, prefissi: bool, dimensione: int | None = None) -> None:
        """La collezione è stata costruita con lo stesso modello e gli stessi prefissi? (slide 10 e 23)"""
        registrati = self.client.get_collection(self.collezione).config.metadata or {}
        differenze = []
        if registrati.get("modello_embedding") != modello:
            differenze.append(f"modello «{registrati.get('modello_embedding')}» nella collezione, «{modello}» configurato")
        if registrati.get("prefissi") != prefissi:
            differenze.append(f"prefissi {registrati.get('prefissi')} nella collezione, {prefissi} configurati")
        if dimensione is not None and registrati.get("dimensione") != dimensione:
            differenze.append(f"dimensione {registrati.get('dimensione')} nella collezione, {dimensione} dal modello")
        if differenze:
            raise ErroreArchivio(
                f"La collezione «{self.collezione}» è stata costruita in un altro modo: " + "; ".join(differenze)
                + ". Cambiare modello richiede di reindicizzare tutto: usare un'altra QDRANT_COLLEZIONE."
            )

    def prepara(self, modello: str, dimensione: int, prefissi: bool) -> None:
        """Crea la collezione se manca, altrimenti controlla che sia compatibile. Non la ricrea mai."""
        if not self.client.collection_exists(self.collezione):
            self.client.create_collection(
                self.collezione,
                vectors_config=models.VectorParams(size=dimensione, distance=models.Distance.COSINE),
                # La collezione ricorda con che cosa è stata costruita: il controllo qui sopra lo rilegge.
                metadata=self._metadati_attesi(modello, dimensione, prefissi),
            )
            # Indici sul payload: rendono efficienti i filtri sui campi usati più spesso (slide 16).
            self.client.create_payload_index(self.collezione, "capitolo", models.PayloadSchemaType.KEYWORD)
            self.client.create_payload_index(self.collezione, "numero", models.PayloadSchemaType.INTEGER)
            return
        self._controlla(modello, prefissi, dimensione)

    def verifica_per_ricerca(self, modello: str, prefissi: bool) -> None:
        if not self.client.collection_exists(self.collezione):
            raise ErroreArchivio(f"La collezione «{self.collezione}» non esiste: eseguire prima l'ingestion "
                                 "(python -m rag.ingestion).")
        self._controlla(modello, prefissi)

    def conta(self) -> int:
        if not self.client.collection_exists(self.collezione):
            return 0
        return self.client.count(self.collezione, exact=True).count

    def capitoli(self) -> list[str]:
        """Valori distinti del campo «capitolo» (facet): servono a controllare il filtro (slide 23)."""
        risposta = self.client.facet(self.collezione, key="capitolo", limit=100)
        return sorted(str(h.value) for h in risposta.hits)

    # ------------------------------------------------------------------ salvataggio ripetibile

    def _tutti_gli_id(self) -> set[str]:
        ids, prossimo = set(), None
        while True:
            punti, prossimo = self.client.scroll(self.collezione, limit=1000, offset=prossimo,
                                                 with_payload=False, with_vectors=False)
            ids.update(str(p.id) for p in punti)
            if prossimo is None:
                return ids

    def salva(self, chunk: list[Chunk], vettori: list[list[float]]) -> EsitoSalvataggio:
        """Upsert con ID stabili, poi rimozione dei punti orfani (scelte 4 e 5 della specifica).

        Stesso chunk → stesso ID → il punto viene sostituito, non duplicato. I punti che non
        corrispondono più a nessun chunk (per esempio perché una ricetta ora ha meno pezzi)
        vengono eliminati: altrimenti resterebbero nella collezione (slide 18).
        """
        punti = [
            models.PointStruct(id=id_punto(c.documento_id, c.posizione), vector=v, payload=payload(c))
            for c, v in zip(chunk, vettori, strict=True)
        ]
        for inizio in range(0, len(punti), _LOTTO_UPSERT):
            self.client.upsert(self.collezione, points=punti[inizio:inizio + _LOTTO_UPSERT], wait=True)
        orfani = sorted(self._tutti_gli_id() - {str(p.id) for p in punti})
        if orfani:
            self.client.delete(self.collezione, points_selector=models.PointIdsList(points=orfani), wait=True)
        return EsitoSalvataggio(scritti=len(punti), rimossi=len(orfani))

    # ------------------------------------------------------------------ ricerca

    def cerca(self, vettore: list[float], k: int = 5, capitolo: str | None = None) -> list[Risultato]:
        if not 1 <= k <= MASSIMO_K:
            raise ValueError(f"k deve essere tra 1 e {MASSIMO_K}: {k}.")
        filtro = None
        if capitolo is not None:
            validi = self.capitoli()
            if capitolo not in validi:
                raise ErroreArchivio(f"Capitolo sconosciuto: «{capitolo}». Capitoli validi: {', '.join(validi)}.")
            # Filtro DURANTE la ricerca (slide 17): Qdrant considera solo i punti del capitolo.
            filtro = models.Filter(must=[models.FieldCondition(key="capitolo", match=models.MatchValue(value=capitolo))])
        risposta = self.client.query_points(self.collezione, query=vettore, limit=k, query_filter=filtro, with_payload=True)
        return [
            Risultato(classifica=i, score=p.score, numero=p.payload["numero"], titolo=p.payload["titolo"],
                      capitolo=p.payload["capitolo"], posizione=p.payload["posizione"],
                      chunk_totali=p.payload["chunk_totali"], testo=p.payload["testo"])
            for i, p in enumerate(risposta.points, start=1)
        ]
