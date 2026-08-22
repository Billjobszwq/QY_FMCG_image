"""认知内核组合根（Task 11）：从 store + 目录构建完整认知服务栈。"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .index.catalog import IndexCatalog
from .index.gateway import CognitiveQueryGateway
from .knowledge.service import KnowledgeService
from .memory.service import MemoryLifecycleService
from .research.citations import CitationVerifier
from .research.service import ResearchService
from .research.synthesizer import Synthesizer
from .skills.service import SkillService
from .sources.service import SourceService


@dataclass
class CognitionStack:
    store: Any
    sources: SourceService
    knowledge: KnowledgeService
    skills: SkillService
    memory: MemoryLifecycleService
    catalog: IndexCatalog
    gateway: CognitiveQueryGateway
    research: ResearchService
    verifier: CitationVerifier
    synthesizer: Synthesizer


def build_cognition_services(store: Any, *, cas_root: Path | str,
                             index_root: Path | str,
                             vector_provider: Any = None,
                             reranker: Any = None) -> CognitionStack:
    sources = SourceService(store, cas_root=cas_root)
    catalog = IndexCatalog(store, index_root=index_root,
                           vector_provider=vector_provider)
    gateway = CognitiveQueryGateway(store, catalog=catalog,
                                    vector_provider=vector_provider,
                                    reranker=reranker)
    verifier = CitationVerifier(store)
    synthesizer = Synthesizer(store)
    return CognitionStack(
        store=store,
        sources=sources,
        knowledge=KnowledgeService(store),
        skills=SkillService(store),
        memory=MemoryLifecycleService(store),
        catalog=catalog,
        gateway=gateway,
        research=ResearchService(store, gateway=gateway,
                                 verifier=verifier,
                                 synthesizer=synthesizer),
        verifier=verifier,
        synthesizer=synthesizer,
    )
