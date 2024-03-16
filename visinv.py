from torch import Tensor, bmm
from torch.nn import Module, Linear, Dropout, ReLU, Sequential, Softmax


class VisualInversion(Module):
    def __init__(self, embed_dim=512, middle_dim=512, output_dim=512, n_layer=2, dropout=0.1):
        super().__init__()
        self.fc_out = Linear(middle_dim, output_dim)
        layers = []
        dim = embed_dim
        for _ in range(n_layer):
            block = [Linear(dim, middle_dim), Dropout(dropout), ReLU()]
            dim = middle_dim
            layers.append(Sequential(*block))        
        self.layers = Sequential(*layers)

    def forward(self, x: Tensor):
        for layer in self.layers:
            x = layer(x)
        return self.fc_out(x)


class MultiHeadCrossAttention(Module):
    def __init__(self, src_dim, tgt_dim, num_heads):
        super().__init__()
        self.num_heads = num_heads
        self.head_dim = tgt_dim // num_heads
        assert self.head_dim * self.num_heads == tgt_dim    # tgt_sim must be divisible by num_heads
        self.q_proj = Linear(src_dim, tgt_dim)
        self.k_proj = Linear(tgt_dim, tgt_dim)
        self.v_proj = Linear(tgt_dim, tgt_dim)
        self.attention_dropout = Dropout(0.1)
        self.softmax = Softmax(dim=-1)
        self.out_proj = Linear(tgt_dim, tgt_dim)

    def _shard(self, tensor, bs):
        return tensor.view(bs, -1, self.num_heads, self.head_dim).transpose(1, 2).contiguous()

    def forward(self, query, target):
        # using the output embedding of text encoder as query, shape is (batch_size, src_dim)
        # target shape is (batch_size, seq_len, tgt_dim)
        batch_size, seq_len, tgt_dim = target.shape

        # Project and shard the queries, keys, and values
        q = self._shard(self.q_proj(query), batch_size)
        k = self._shard(self.k_proj(target), batch_size)
        v = self._shard(self.v_proj(target), batch_size)

        # Calculate the attention scores
        q = q.expand(-1, -1, seq_len, -1).contiguous().view(batch_size * self.num_heads, -1, self.head_dim)     # [bs*num_heads, seq_len, head_dim]
        k = k.view(batch_size * self.num_heads, -1, self.head_dim).transpose(-2, -1)    # [bs*num_heads, head_dim, seq_len]
        scores = bmm(q, k) / (self.head_dim ** 0.5)      # [bs*num_heads, seq_len, seq_len]
        scores = self.softmax(scores)
        scores = self.attention_dropout(scores)

        # Apply the attention to the values
        v = v.view(batch_size * self.num_heads, -1, self.head_dim)  # [bs*num_heads, seq_len, head_dim]
        context = bmm(scores, v)    # [bs*num_heads, seq_len, head_dim]
        context = context.transpose(1, 2).contiguous().view(batch_size, seq_len, -1)  # [bs, seq_len, tgt_dim] todo is this correct?

        # Project the context to the original query shape
        attention_output = self.out_proj(context)
        return attention_output     # [bs, seq_len, tgt_dim]
