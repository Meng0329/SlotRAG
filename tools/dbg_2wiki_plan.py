import json, sys
from pathlib import Path
sys.path.insert(0, 'src')
sys.path.insert(0, '.')

from slotrag.config import AppConfig
from slotrag.models import SlotPlan
from slotrag.data import chunk_passages
from slotrag.providers import provider_clients
from slotrag.retrieval import EmbeddingCache, HybridRetriever
from slotrag.benchmarking.runner import _BudgetedAgnes, _BudgetedRetriever
from slotrag.benchmarking.methods import run_method
from tools.run_confirmatory import load_question

manifest = [json.loads(l) for l in open('research/hstruct_confirmatory/confirmatory_eligible_manifest.jsonl')]
item = [i for i in manifest if i['dataset'] == '2wikimultihop'][0]
config = AppConfig.from_yaml(Path('configs/default.yaml'))
q = load_question('2wikimultihop', item['question_id'], item.get('source_split', 'validation'))
plan = SlotPlan.model_validate_json(item['plan_json'])

agnes, embedding, reranker = provider_clients(config)
passages = chunk_passages(
    q.passages,
    chunk_tokens=config.retrieval.chunk_tokens,
    overlap=config.retrieval.chunk_overlap,
)
retriever = HybridRetriever(
    passages, embedding, reranker,
    bm25_k=config.retrieval.bm25_k, dense_k=config.retrieval.dense_k,
    final_k=config.retrieval.final_k, rrf_k=config.retrieval.rrf_k,
    bm25_weight=config.retrieval.bm25_weight, dense_weight=config.retrieval.dense_weight,
    rerank_enabled=config.reranker.enabled, cache=EmbeddingCache(), dense_enabled=True,
    sparse_index_mode=config.retrieval.sparse_index_mode,
    sparse_title_weight=config.retrieval.sparse_title_weight,
)
retriever.build_index()

res = run_method(
    'slotrag-g7-chain', dataset='2wikimultihop', question=q,
    retriever=_BudgetedRetriever(retriever, 8), client=_BudgetedAgnes(agnes, 96),
    config=config, seed=2027, max_steps=8, max_retrieval_calls=8, frozen_plan=plan,
)

print('status:', res.status)
print('error:', repr(res.error))
print('answer:', repr((res.answer or '')[:120]))
mt = res.metrics
if mt:
    print('orders:', getattr(mt, 'slot_execution_orders', None))
    print('plan_order_mismatches:', getattr(mt, 'physical_plan_order_mismatches', None))
    print('frontier_guard_checks:', getattr(mt, 'frontier_guard_checks', None))
    print('frontier_guard_interventions:', getattr(mt, 'frontier_guard_interventions', None))