## Hybrid Retrieval Pipeline and Out-of-Distribution Evaluation

Our retrieval pipeline combines four established components: BM25 sparse scoring (Robertson and Zaragoza, 2009), Contriever dense passage embeddings (Izacard et al., 2022), Reciprocal Rank Fusion with fixed constant k = 60 (Cormack et al., 2009), and top-k cross-encoder reranking (Nogueira and Cho, 2019).

Across five out-of-distribution datasets in BEIR-OOD-Subset-v1, rank-only Reciprocal Rank Fusion attains 0.482 macro NDCG@10 compared with 0.449 macro NDCG@10 for uncalibrated min-max linear score fusion. We make no claim of a new retrieval architecture; the empirical scope is limited to measuring rank aggregation versus score normalization on a fixed candidate pool.
