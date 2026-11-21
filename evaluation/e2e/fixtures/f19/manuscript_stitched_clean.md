# Degree-Aware Scaling Evaluation

## Abstract

On citation graphs under degree shift, combining a two-layer GCN with one degree-aware L2 scaling parameter reached 0.752 macro-F1 compared with 0.718 macro-F1 for the unmodified two-layer GCN baseline across five random seeds.

## Results

The unmodified two-layer GCN baseline scored 0.718 macro-F1 under matched hyperparameter tuning.
Adding the single degree-aware scaling coefficient raised held-out score to 0.752 macro-F1, yielding a 0.034 gain across five fixed seeds.
Removing the scaling coefficient returned performance to the baseline level, showing no need for extra encoders or auxiliary losses.
