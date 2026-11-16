"""Salvataggio delle chat con SQLAlchemy (slide 14: «le salva in PostgreSQL»).

Le due tabelle sono classi Python (ORM = Object-Relational Mapping): una riga della tabella
`chat` è un oggetto Chat, una riga di `messaggio` è un oggetto Messaggio.

    chat 1 ──── N messaggio        (una chat ha molti messaggi; eliminata la chat, spariscono)

Lo stesso codice gira su PostgreSQL (applicazione) e su SQLite (test automatici): cambia solo
l'indirizzo passato ad Archivio.
"""

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, relationship
from sqlalchemy.pool import StaticPool

TITOLO_INIZIALE = "Nuova chat"
LUNGHEZZA_TITOLO = 60


def ora_utc() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Chat(Base):
    __tablename__ = "chat"

    # UUID e non un numero progressivo: l'identificativo finisce negli indirizzi (/chat/<id>) e non
    # deve far capire quante chat esistono.
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    titolo: Mapped[str] = mapped_column(String(LUNGHEZZA_TITOLO), default=TITOLO_INIZIALE)
    creata_il: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    aggiornata_il: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # data dell'ultimo messaggio
    # Step 3: il riassunto prodotto dall'agente e quanti messaggi, dai più vecchi, copre. I messaggi
    # restano tutti nel database (l'utente li vede); all'agente si mandano solo quelli non coperti.
    riassunto: Mapped[str] = mapped_column(Text, default="")
    messaggi_riassunti: Mapped[int] = mapped_column(Integer, default=0)

    # cascade: eliminando la chat SQLAlchemy elimina anche i suoi messaggi (slide 14, ultima riga).
    messaggi: Mapped[list["Messaggio"]] = relationship(
        back_populates="chat", cascade="all, delete-orphan", order_by="Messaggio.id"
    )


class Messaggio(Base):
    __tablename__ = "messaggio"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)  # crescente = ordine cronologico
    chat_id: Mapped[str] = mapped_column(ForeignKey("chat.id", ondelete="CASCADE"), index=True)
    ruolo: Mapped[str] = mapped_column(String(16))  # «utente» oppure «assistente»
    testo: Mapped[str] = mapped_column(Text)
    creato_il: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    strumenti: Mapped[list] = mapped_column(JSON, default=list)  # strumenti usati dall'agente per questa risposta

    chat: Mapped[Chat] = relationship(back_populates="messaggi")


# ---------------------------------------------------------------------- dagli oggetti ai dizionari per l'API

def _iso(istante: datetime) -> str:
    # SQLite restituisce date senza fuso: sono sempre state salvate in UTC.
    if istante.tzinfo is None:
        istante = istante.replace(tzinfo=timezone.utc)
    return istante.isoformat()


def _chat_breve(chat: Chat, numero_messaggi: int) -> dict:
    return {
        "id": chat.id,
        "titolo": chat.titolo,
        "creata_il": _iso(chat.creata_il),
        "aggiornata_il": _iso(chat.aggiornata_il),
        "numero_messaggi": numero_messaggi,
    }


def _messaggio(m: Messaggio) -> dict:
    return {"id": m.id, "ruolo": m.ruolo, "testo": m.testo, "creato_il": _iso(m.creato_il), "strumenti": m.strumenti or []}


def titolo_da(domanda: str) -> str:
    """Titolo della chat: la prima domanda su una riga sola, tagliata a 60 caratteri."""
    return " ".join(domanda.split())[:LUNGHEZZA_TITOLO] or TITOLO_INIZIALE


class Archivio:
    """Tutte le operazioni sulle chat. Ogni metodo apre una sessione breve e la chiude."""

    def __init__(self, url: str, adesso: Callable[[], datetime] = ora_utc):
        opzioni = {}
        if url.startswith("sqlite"):
            # Solo per i test: FastAPI usa più thread, e il database in memoria deve essere uno solo.
            opzioni["connect_args"] = {"check_same_thread": False}
            if url in ("sqlite://", "sqlite:///:memory:"):
                opzioni["poolclass"] = StaticPool
        # pool_pre_ping: prima di usare una connessione controlla che sia viva (utile se PostgreSQL riparte).
        self._motore = create_engine(url, pool_pre_ping=True, **opzioni)
        self._adesso = adesso

    def prepara(self) -> None:
        """Crea le tabelle se non esistono. Solleva un errore se il database non è raggiungibile."""
        Base.metadata.create_all(self._motore)

    def chiudi(self) -> None:
        self._motore.dispose()

    def raggiungibile(self) -> bool:
        try:
            with self._motore.connect() as connessione:
                connessione.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------ le operazioni della slide 14

    def crea_chat(self) -> dict:
        with Session(self._motore) as sessione:
            istante = self._adesso()
            chat = Chat(creata_il=istante, aggiornata_il=istante)
            sessione.add(chat)
            sessione.commit()
            return _chat_breve(chat, 0)

    def elenco(self) -> list[dict]:
        """Tutte le chat, dalla più recente, con il numero di messaggi (senza i messaggi)."""
        with Session(self._motore) as sessione:
            righe = sessione.execute(
                select(Chat, func.count(Messaggio.id))
                .outerjoin(Messaggio)
                .group_by(Chat.id)
                .order_by(Chat.aggiornata_il.desc())
            ).all()
            return [_chat_breve(chat, numero) for chat, numero in righe]

    def leggi(self, chat_id: str) -> dict | None:
        """La chat con i messaggi in ordine cronologico; None se non esiste."""
        with Session(self._motore) as sessione:
            chat = sessione.get(Chat, chat_id)
            if chat is None:
                return None
            return {**_chat_breve(chat, len(chat.messaggi)), "messaggi": [_messaggio(m) for m in chat.messaggi]}

    def elimina(self, chat_id: str) -> bool:
        with Session(self._motore) as sessione:
            chat = sessione.get(Chat, chat_id)
            if chat is None:
                return False
            sessione.delete(chat)
            sessione.commit()
            return True

    # ------------------------------------------------------------------ invio di un messaggio, in due tempi

    def contesto_per_agente(self, chat_id: str) -> tuple[list[dict], str] | None:
        """Ciò che va mandato all'agente: i messaggi non coperti dal riassunto, e il riassunto."""
        with Session(self._motore) as sessione:
            chat = sessione.get(Chat, chat_id)
            if chat is None:
                return None
            recenti = chat.messaggi[chat.messaggi_riassunti:]
            return [{"ruolo": m.ruolo, "testo": m.testo} for m in recenti], chat.riassunto

    def salva_scambio(self, chat_id: str, domanda: str, risposta: str, strumenti: list,
                      riassunto: str, nuovi_riassunti: int) -> dict | None:
        """Salva domanda e risposta INSIEME, in una sola transazione (o entrambe o nessuna).

        Si chiama solo dopo che l'agente ha risposto: se l'agente è spento non si salva nulla e
        la chat resta com'era. None se nel frattempo la chat è stata eliminata.
        """
        with Session(self._motore) as sessione:
            chat = sessione.get(Chat, chat_id)
            if chat is None:
                return None
            if not chat.messaggi:
                chat.titolo = titolo_da(domanda)
            m_domanda = Messaggio(ruolo="utente", testo=domanda, creato_il=self._adesso(), strumenti=[])
            m_risposta = Messaggio(ruolo="assistente", testo=risposta, creato_il=self._adesso(), strumenti=strumenti)
            # I due nuovi messaggi non possono essere già riassunti: il conteggio si ferma prima.
            chat.messaggi_riassunti = min(chat.messaggi_riassunti + nuovi_riassunti, len(chat.messaggi))
            chat.messaggi += [m_domanda, m_risposta]
            chat.riassunto = riassunto
            chat.aggiornata_il = m_risposta.creato_il
            sessione.commit()
            return {
                "domanda": _messaggio(m_domanda),
                "risposta": _messaggio(m_risposta),
                "chat": _chat_breve(chat, len(chat.messaggi)),
            }

    def numero_messaggi_totale(self) -> int:
        with Session(self._motore) as sessione:
            return sessione.scalar(select(func.count(Messaggio.id))) or 0
