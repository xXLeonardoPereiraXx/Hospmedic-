"""Cancelamento cooperativo de análises longas.

Python não permite matar uma thread de fora com segurança: interromper no meio
de uma escrita de arquivo ou de uma estrutura pela metade deixaria o processo
inconsistente. O cancelamento aqui é **cooperativo** — quem executa o trabalho
verifica, em pontos seguros, se foi cancelado e encerra por conta própria.

O ponto de verificação natural é a troca de página do PDF: é onde o tempo é
gasto (dezenas de páginas, cada uma com extração de texto) e onde não há nada
pela metade. Na prática, cancelar interrompe em menos de uma página.

Cada análise roda em sua própria thread, então o registro é por identificador
de thread — nenhuma análise interfere na outra.
"""
from __future__ import annotations

import threading


class AnaliseCancelada(Exception):
    """Sinaliza que a análise foi interrompida a pedido do usuário."""


_CANCELADAS: set[int] = set()
_LOCK = threading.Lock()


def marcar_cancelamento(thread_id: int) -> None:
    """Pede o cancelamento da análise que roda na thread indicada."""
    with _LOCK:
        _CANCELADAS.add(thread_id)


def limpar(thread_id: int) -> None:
    """Remove o registro da thread (ao terminar ou ao ser cancelada)."""
    with _LOCK:
        _CANCELADAS.discard(thread_id)


def cancelada(thread_id: int | None = None) -> bool:
    tid = thread_id if thread_id is not None else threading.get_ident()
    with _LOCK:
        return tid in _CANCELADAS


def checar() -> None:
    """Levanta :class:`AnaliseCancelada` se a thread atual foi cancelada.

    Chamada nos pontos seguros do processamento; fora de uma análise cancelada
    o custo é o de uma consulta a um conjunto em memória.
    """
    if cancelada():
        raise AnaliseCancelada("Análise cancelada pelo usuário.")
