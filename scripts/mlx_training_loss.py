"""Compute the full-vocabulary head only for supervised completion positions."""

import mlx.core as mx
import mlx.nn as nn


COMPLETION_BUDGET = 512


def completion_loss(model, batch, lengths):
    hidden = model.language_model.model(batch[:, :-1])
    count = min(COMPLETION_BUDGET, hidden.shape[1])
    positions = lengths[:, :1] - 1 + mx.arange(count)[None, :]
    valid = (positions >= 0) & (positions + 1 < lengths[:, 1:2])
    safe = mx.clip(positions, 0, hidden.shape[1] - 1)
    hidden = mx.take_along_axis(hidden, safe[..., None], axis=1)
    language_model = model.language_model
    if language_model.args.tie_word_embeddings:
        logits = language_model.model.embed_tokens.as_linear(hidden)
    else:
        logits = language_model.lm_head(hidden)
    targets = mx.take_along_axis(batch[:, 1:], safe, axis=1)
    losses = nn.losses.cross_entropy(logits, targets)
    tokens = valid.sum()
    return (losses * valid).astype(mx.float32).sum() / tokens, tokens
